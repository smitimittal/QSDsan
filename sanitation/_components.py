#!/usr/bin/env python3
# -*- coding: utf-8 -*-

'''
Sanitation Explorer: Sustainable design of non-sewered sanitation technologies
Copyright (C) 2020, Sanitation Explorer Development Group

This module is developed by:
    Yalin Li <zoe.yalin.li@gmail.com>
    Joy Cheung

This module is under the UIUC open-source license. See 
https://github.com/QSD-for-WaSH/sanitation/blob/master/LICENSE.txt
for license details.
'''

import numpy as np
import pandas as pd
import thermosteam as tmo
from thermosteam import Chemical, Chemicals, CompiledChemicals
from . import _component

__all__ = ('Components', 'CompiledComponents')

utils = tmo.utils
Component = _component.Component
_component_properties = _component._component_properties
_num_component_properties = _component._num_component_properties
_key_component_properties = _component._key_component_properties
setattr = object.__setattr__


# %%

class UndefinedComponent(AttributeError):
    '''AttributeError regarding undefined Component objects.'''
    def __init__(self, ID): super(Chemical, self).__init__(repr(ID))

# =============================================================================
# Define the Components class
# =============================================================================

class Components(Chemicals):
    '''
    A subclass of the Chemicals object in the thermosteam package,
    contains Component objects as attributes.
    '''
    
    def __new__(cls, components, cache=False):
        self = super(Chemicals, cls).__new__(cls)
        isa = isinstance
        setfield = setattr
        for component in components:
            if isa(component, Component):
                setfield(self, component.ID, component)
            else:
                if isa(component, Chemical):
                    raise TypeError(f'{component} is a Chemical object, use Component.from_chemical to define a Component object.')
                raise TypeError(f'Only Component objects can be included, not a {type(component).__name__} object.')
        return self
    
    def __setattr__(self, ID, component):
        raise TypeError("Cannot set attribute; use {self.ID}.append instead.")
    
    def __setitem__(self, ID, component):
        raise TypeError("Cannot set item; use {self.ID}.append instead.")
    
    def __getitem__(self, key):
        '''Return a Component object or a list of Component objects.'''
        dct = self.__dict__
        try:
            if isinstance(key, str):
                return dct[key]
            else:
                return [dct[i] for i in key]
        except KeyError as key_error:
            raise UndefinedComponent(key_error.args[0])
    
    def __contains__(self, component):
        if isinstance(component, str):
            return component in self.__dict__
        elif isinstance(component, Component):
            return component in self.__dict__.values()
        else: # pragma: no cover
            return False        
    
    def append(self, component):
        '''Append a Component'''
        if not isinstance(component, Component):
            if isinstance(component, Chemical):
                raise TypeError(f'{component} is a Chemical object, use Component.from_chemical to define a Component object.')
            else:
                raise TypeError("only Component objects can be appended, "
                               f"not {type(component).__name__} object.")
        ID = component.ID
        if ID in self.__dict__:
            raise ValueError(f"{ID} already defined in Components.")
        setattr(self, ID, component)
    
    def extend(self, components):
        '''Extend with more Component objects.'''
        if isinstance(components, Components):
            self.__dict__.update(components.__dict__)
        else:
            for component in components: self.append(component)
    
    def compile(self):
        '''Cast as a CompiledComponents object.'''
        CompiledComponents._compile(self)
        setattr(self, '__class__', CompiledComponents)
        
    
    @classmethod
    def load_from_file(cls, file_type='', path=''):
        '''
        Create Component objects based on properties defined in a cvs or an Excel file,
        return a Components object that contains all created Component objects.
    
        Parameters
        ----------
        file_type : [str]
            File type, 'cvs' or 'Excel'.
        path : [str]
            File path.
    
        Returns
        -------
        A Components object that contains all created Component objects.
            
        Notes
        -------
        The Components object needs to be compiled before it is used in simulation
    
        '''
        if file_type=='cvs':
            data = pd.read_csv(path)
        elif file_type in ('Excel', 'excel'):
            data = pd.read_excel(path)
        else:
            raise ValueError(f"file_type can only be 'cvs' or 'Excel', not {file_type}.")
        new = cls(())

        for i, cmp in data.iterrows():
            if pd.isna(cmp.measured_as):
                cmp.measured_as = None
            try:
                component = Component(ID = cmp.ID, 
                                      search_ID = str(cmp.CAS), 
                                      measured_as = cmp.measured_as)
            except LookupError:
                try:
                    component = Component(ID = cmp.ID, 
                                          search_ID = 'PubChem='+str(int(cmp.PubChem)),
                                          measured_as = cmp.measured_as) 
                except:
                    if not pd.isna(cmp.formula):
                        component = Component(ID = cmp.ID,
                                              formula = cmp.formula, 
                                              measured_as = cmp.measured_as)            
                    else:
                        component = Component(ID = cmp.ID, 
                                              measured_as = cmp.measured_as)
            for j in _component_properties:
                field = '_' + j
                if pd.isna(cmp[j]): continue
                setattr(component, field, cmp[j])
            new.append(component)

        del data
        return new
    
    
    @classmethod
    def load_default(cls, default_compile=True):
        '''
        Create a Components object containing default Component objects.
    
        Parameters
        ----------
        default_compile : [bool], optional
            Whether to compile the default Components. The default is True.
    
        Returns
        -------
        A Components or CompiledComponents object with default Component objects.
    
        Notes
        -------
        [1] Component-specific properties are defined in ./default_data/_component.cvs.
        [2] When default_compile is True, all essential Chemical-specific properties 
            that are missing will be defaulted to those of water.
    
        '''
        import os
        path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'default_data/_components.csv')
        new = cls.load_from_file(file_type='cvs', path=path)

        H2O = Component.from_chemical('H2O', tmo.Chemical('H2O'),
                          i_C=0, i_N=0, i_P=0, i_K=0, i_mass=1,
                          i_charge=0, f_BOD5_COD=0, f_uBOD_COD=0,
                          f_Vmass_Totmass=0,
                          particle_size='Soluble',
                          degradability='Undegradable', organic=False)
        new.append(H2O)
        
        if default_compile:
            TMH = tmo.base.thermo_model_handle.ThermoModelHandle
            for i in new:
                i.default()
                for j in ('sigma', 'epsilon', 'kappa', 'V', 'Cn', 'mu'):
                    if isinstance(getattr(i, j), TMH) and len(getattr(i, j).models) > 0: continue
                    i.copy_models_from(H2O, names=(j,))
        
        return new        


# %%

# =============================================================================
# Define the CompiledComponents class
# =============================================================================

chemical_data_array = tmo._chemicals.chemical_data_array

def component_data_array(components, attr):
    data = chemical_data_array(components, attr)
    return data

class CompiledComponents(CompiledChemicals):
    '''
    A subclass of the CompiledChemicals object in the thermosteam package,
    contains Component objects as attributes.'''
    
    _cache = {}
    
    def __new__(cls, components, cache=None):
        isa = isinstance
        components = tuple([cmp if isa(cmp, Component) else Component(cmp, cache)
                           for cmp in components])        
        cache = cls._cache
        if components in cache:
            self = cache[components]
        else:
            self = object.__new__(cls)
            setfield = setattr
            for cmp in components:
                setfield(self, cmp.ID, cmp)
            self._compile()
            cache[components] = self
        return self    
    
    def refresh_constants(self):
        '''
        Refresh constant arrays of Components,
        including all Chemical and Component-specific properties.
        '''
        super().refresh_constants()
        dct = self.__dict__
        components = self.tuple
        for i in _num_component_properties:
            dct[i] = component_data_array(components, i)

    def _compile(self):
        dct = self.__dict__
        tuple_ = tuple # to differentiate it from dct['tuple']?
        components = tuple_(dct.values())
        CompiledChemicals._compile(self)
        
        for component in components:
            missing_properties = component.get_missing_properties(_key_component_properties)
            if not missing_properties: continue
            missing = utils.repr_listed_values(missing_properties)
            raise RuntimeError(f'{component} is missing key Component-related properties ({missing}).')

        for i in _num_component_properties:
            dct[i] = component_data_array(components, i)
        
        dct['s'] = np.asarray([1 if cmp.particle_size == 'Soluble' else 0 for cmp in components])
        dct['c'] = np.asarray([1 if cmp.particle_size == 'Colloidal' else 0 for cmp in components])
        dct['x'] = np.asarray([1 if cmp.particle_size == 'Particulate' else 0 for cmp in components])
        dct['b'] = np.asarray([1 if cmp.degradability != 'Undegradable' else 0 for cmp in components])
        dct['org'] = np.asarray([int(cmp.organic) for cmp in components])
    
    def subgroup(self, IDs):
        '''Create a new subgroup of Component objects.'''
        components = self[IDs]
        new = Components(components)
        new.compile()
        for i in new.IDs:
            for j in self.get_synonyms(i):
                try: new.set_synonym(i, j)
                except: pass
        return new
    
    def index(self, ID):
        '''Return index of specified Component.'''
        try: return self._index[ID]
        except KeyError:
            raise UndefinedComponent(ID)

    def indices(self, IDs):
        try:
            dct = self._index
            return [dct[i] for i in IDs]
        except KeyError as key_error:
            raise UndefinedComponent(key_error.args[0])
    
    def __contains__(self, component):
        if isinstance(component, str):
            return component in self.__dict__
        elif isinstance(component, Component):
            return component in self.tuple
        else: # pragma: no cover
            return False
    
    