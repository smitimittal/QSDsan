# -*- coding: utf-8 -*-
'''
QSDsan: Quantitative Sustainable Design for sanitation and resource recovery systems
Copyright (C) 2020, Quantitative Sustainable Design Group

This module is developed by:
    Joy Cheung <joycheung1994@gmail.com>

This module is under the UIUC open-source license. Please refer to 
https://github.com/QSD-Group/QSDsan/blob/master/LICENSE.txt
for license details.
'''

# import thermosteam as tmo
from ._parse import get_stoichiometric_coeff
from . import Components
from thermosteam.utils import chemicals_user, read_only
from sympy import symbols, Matrix
from sympy.parsing.sympy_parser import parse_expr
import numpy as np
import pandas as pd
    
__all__ = ('Process', 'Processes', 'CompiledProcesses', )

class UndefinedProcess(AttributeError):
    '''AttributeError regarding undefined Component objects.'''
    def __init__(self, ID):
        super().__init__(repr(ID))
        
#%%
@chemicals_user        
class Process():
    
    def __init__(self, ID, reaction, ref_component, rate_equation=None, components=None, 
                 conserved_for=('COD', 'N', 'P', 'charge'), parameters=None):
        """
        Create a ``Process`` object which defines a stoichiometric process and its kinetics.
        A ``Process`` object is capable of reacting the component flow rates of a ``WasteStream``
        object.

        Parameters
        ----------
        ID : str
            A unique identification.
        reaction : dict, str, or numpy.ndarray
            A dictionary of stoichiometric coefficients with component IDs as 
            keys, or a numeric array of stoichiometric coefficients, or a string 
            of a stoichiometric equation written as: 
            i1 R1 + ... + in Rn -> j1 P1 + ... + jm Pm.
            Stoichiometric coefficients can be symbolic or numerical. 
            Unknown stoichiometric coefficients to solve for should be expressed as '?'.
        ref_component : str
            ID of the reference ``Component`` object of the process rate.
        rate_equation : str, optional
            The kinetic rate equation of the process. The default is None.
        components=None : ``CompiledComponents``, optional
            Components corresponding to each entry in the stoichiometry array, 
            defaults to thermosteam.settings.chemicals. 
        conserved_for : tuple[str], optional
            Materials subject to conservation rules, must be an 'i_' attribute of
            the components. The default is ('COD', 'N', 'P', 'charge').
        parameters : Iterable[str], optional
            Symbolic parameters in stoichiometry coefficients and/or rate equation. 
            The default is None.

        Examples
        --------
        None.

        """
        self._ID = ID
        self._stoichiometry = []
        self._components = self._load_chemicals(components)
        self._ref_component = ref_component
        self._conserved_for = conserved_for
        self._parameters = {p: symbols(p) for p in parameters}
        
        self._stoichiometry = get_stoichiometric_coeff(reaction, self._ref_component, self._components, self._conserved_for, self._parameters)
        self._parse_rate_eq(rate_equation)
                
    def get_conversion_factors(self, as_matrix=False):        
        '''
        return conversion factors (i.e., the 'i_' attributes of the components) 
        as a numpy.ndarray or a SymPy Matrix.
        '''
        if self._conservation_for:
            cmps = self._components
            arr = getattr(cmps, 'i_'+self._conservation_for[0])
            for c in self._conservation_for[1:]:
                arr = np.vstack((arr, getattr(cmps, 'i_'+c)))
            if as_matrix: return Matrix(arr.tolist())
            return arr
        else: return None
                    
    def check_conservation(self, tol=1e-8):
        '''check conservation of materials given numerical stoichiometric coefficients. '''
        isa = isinstance
        if isa(self._stoichiometry, np.ndarray):
            ic = self.get_conversion_factors()
            v = self._stoichiometry
            ic_dot_v = ic @ v
            conserved_arr = np.isclose(ic_dot_v, np.zeros(ic_dot_v.shape), atol=tol)
            if not conserved_arr.all(): 
                materials = self._conserved_for
                unconserved = [(materials[i], ic_dot_v[i]) for i, conserved in enumerate(conserved_arr) if not conserved]
                raise RuntimeError("The following materials are unconserved by the "
                                   "stoichiometric coefficients. A positive value "
                                   "means the material is created, a negative value "
                                   "means the material is destroyed:\n "
                                   + "\n ".join([f"{material}: {value:.2f}" for material, value in unconserved]))
        else: 
            raise RuntimeError("Can only check conservations with numerical "
                               "stoichiometric coefficients.")
    
    def reverse(self):
        '''reverse the process as to flip the signs of stoichiometric coefficients of all components.'''
        if isinstance(self._stoichiometry, np.ndarray):
            self._stoichiometry = -self._stoichiometry
        else:
            self._stoichiometry = [-v for v in self._stoichiometry]
        self._rate_equation = -self._rate_equation
        
    @property
    def ID(self):
        '''[str] A unique identification'''
        return self._ID
    
    @property
    def ref_component(self):
        '''
        [str] ID of the reference component
        
        Note
        ----
        When a new value is assigned, all stoichiometric coefficient will be 
        normalized so that the new stoichiometric coefficient of the new reference
        component is 1 or -1. The rate equation will also be updated automatically.
        '''
        return getattr(self._components, self._ref_component)    
    @ref_component.setter
    def ref_component(self, ref_cmp):
        if ref_cmp: 
            self._ref_component = ref_cmp
            self._normalize_stoichiometry(ref_cmp)
            self._normalize_rate_eq(ref_cmp)

    @property
    def conserved_for(self):
        '''
        [tuple] Materials subject to conservation rules, must have corresponding 
        'i_' attributes for the components
        '''
        return self._conserved_for
    @conserved_for.setter
    def conserved_for(self, materials):
        self._conserved_for = materials
    
    @property
    def parameters(self):
        '''[list] Symbolic parameters in stoichiometric coefficients and rate equation.'''
        return tuple(sorted(self._parameters))
    
    def append_parameters(self, *new_pars):
        '''append new symbolic parameters'''
        for p in new_pars:
            self._parameters[p] = symbols(p)
    
    #TODO: set parameter values (and evaluate coefficients and rate??)
    def set_parameters(self):
        pass
    
    @property
    def stoichiometry(self):
        '''[dict] Non-zero stoichiometric coefficients.'''
        allcmps = dict(zip(self._components.IDs, self._stoichiometry))
        return {k:v for k,v in allcmps.items() if v != 0}
        
    @property
    def rate_equation(self):
        '''
        [SymPy expression] Kinetic rate equation of the process. Also the rate in
        which the reference component is reacted or produced in the process.
        '''
        return self._rate_equation
    
    def _parse_rate_eq(self, eq):
        cmpconc_symbols = {c: symbols(c) for c in self._components.IDs}
        self._rate_equation = parse_expr(eq, {**cmpconc_symbols, **self._parameters})
    
    def _normalize_stoichiometry(self, new_ref):
        isa = isinstance
        factor = abs(self._stoichiometry[self._components._index[new_ref]])
        if isa(self._stoichiometry, np.ndarray):
            self._stoichiometry /= factor
        elif isa(self._stoichiometry, list):
            self._stoichiometry = [v/factor for v in self._stoichiometry]
    
    def _normalize_rate_eq(self, new_ref):
        factor = self._stoichiometry[self._components._index[new_ref]]
        self._rate_equation *= factor

#%%
setattr = object.__setattr__
@chemicals_user
class Processes():
    
    def __new__(cls, processes):
        """
        Create a ``Processes`` object that contains ``Process`` objects as attributes.

        Parameters
        ----------
        processes : Iterable[``Process``]

        Examples
        --------
        None.

        """
        self = super().__new__(cls)
        #!!! add function to detect duplicated processes
        setfield = setattr
        for i in processes:
            setfield(self, i.ID, i)
        return self
    
    # def __getnewargs__(self):
    #     return(tuple(self),)
    
    def __setattr__(self, ID, process):
        raise TypeError("can't set attribute; use <Processes>.append instead")
    
    def __setitem__(self, ID, process):
        raise TypeError("can't set attribute; use <Processes>.append instead")
    
    def __getitem__(self, key):
        """
        Return a ``Process`` or a list of ``Process`` objects.
        
        Parameters
        ----------
        key : Iterable[str] or str
              Process IDs.
        
        """
        dct = self.__dict__
        try:
            if isinstance(key, str):
                return dct[key]
            else:
                return [dct[i] for i in key]
        except KeyError:
            raise KeyError(f"undefined process {key}")
    
    def copy(self):
        """Return a copy."""
        copy = object.__new__(Processes)
        for proc in self: setattr(copy, proc.ID, proc)
        return copy
    
    def append(self, process):
        """Append a ``Process``."""
        if not isinstance(process, Process):
            raise TypeError("only 'Process' objects can be appended, "
                           f"not '{type(process).__name__}'")
        ID = process.ID
        if ID in self.__dict__:
            raise ValueError(f"{ID} already defined in processes")
        setattr(self, ID, process)
    
    def extend(self, processes):
        """Extend with more ``Process`` objects."""
        if isinstance(processes, Processes):
            self.__dict__.update(processes.__dict__)
        else:
            for process in processes: self.append(process)
    
    def subgroup(self, IDs):
        """
        Create a new subgroup of processes.
        
        Parameters
        ----------
        IDs : Iterable[str]
              Process IDs.
              
        """
        return Process([getattr(self, i) for i in IDs])
    
    def mycompile(self):
        '''Cast as a ``CompiledProcesses`` object.'''
        setattr(self, '__class__', CompiledProcesses)
        CompiledProcesses._compile(self)
        
    # kwarray = array = index = indices = must_compile
        
    def show(self):
        print(self)
    
    _ipython_display_ = show
    
    def __len__(self):
        return len(self.__dict__)
    
    def __contains__(self, process):
        if isinstance(process, str):
            return process in self.__dict__
        elif isinstance(process, Process):
            return process in self.__dict__.values()
        else: # pragma: no cover
            return False
    
    def __iter__(self):
        yield from self.__dict__.values()
    
    def __repr__(self):
        return f"{type(self).__name__}([{', '.join(self.__dict__)}])"
    
    _default_data = None
    
    @classmethod
    def load_from_file(cls, path='', components=None, 
                       conserved_for=('COD', 'N', 'P', 'charge'), parameters=None,
                       use_default_data=False, store_data=False, compile=True):
        """
        Create ``CompiledProcesses`` object from a table of process IDs, stoichiometric 
        coefficients, and rate equations stored in a .csv or Excel file. 

        Parameters
        ----------
        path : str, optional
            File path.
        components : ``CompiledComponents``, optional
            Components corresponding to the columns in the stoichiometry matrix, 
            defaults to thermosteam.settings.chemicals. The default is None.
        conserved_for : tuple[str], optional
            Materials subject to conservation rules, must have corresponding 'i_' 
            attributes for the components. The default is ('COD', 'N', 'P', 'charge').
        parameters : Iterable[str], optional
            Symbolic parameters in waste. The default is None.
        use_default_data : bool, optional
            Whether to use default data. The default is False.
        store_data : bool, optional
            Whether to store the file as default data. The default is False.
        compile : bool, optional
            Whether to compile processes. The default is True.

        Note
        ----
        [1] First column of the table should be process IDs, followed by stoichiometric 
            coefficient matrix with corresponding component IDs as column names, and rate 
            equations as the last column. 
        
        [2] Entries of stoichiometric coefficients can be symbolic or numerical. 
            Blank cells are considered zero.
        
        [3] Unknown stoichiometric coefficients to solve for using conservation 
            rules should be uniformly written as '?'. 
        
        [4] For each process, the first component with stoichiometric coefficient
            of -1 or 1 is considered the reference component. If none of the components
            has -1 or 1 stoichiometric coefficient, the first component with non-zero
            coefficient is considered the reference.
        """
        if use_default_data and cls._default_data is not None:
            data = cls._default_data
        else:
            if path.endswith('.csv'): data = pd.read_csv(path, na_values=0)
            elif path.endswith(('.xls', '.xlsx')): data = pd.read_excel(path, na_values=0)
            else: raise ValueError('Only .csv or Excel files can be used.')
        
        cmp_IDs = data.columns[1:-1]
        data.dropna(how='all', subset=cmp_IDs, inplace=True)
        new = cls(())
        for i, proc in data.iterrows():
            ID = proc[1]
            stoichio = proc[1:-1]
            if pd.isna(proc[-1]): rate_eq = None
            else: rate_eq = proc[-1]
            ref = cmp_IDs[stoichio.isin((-1, 1))]
            if len(ref) == 0: ref = cmp_IDs[-pd.isna(stoichio)][0]                
            else: ref = ref[0]
            stoichio = stoichio[-pd.isna(stoichio)]
            process = Process(ID, stoichio.to_dict(), 
                              ref_component=ref, 
                              rate_equation=rate_eq,
                              conserved_for=conserved_for,
                              parameters=parameters)
            new.append(process)

        if store_data:
            cls._default_data = data
        
        if compile: new.mycompile()
        return new
        
            
#%%
@read_only(methods=('append', 'extend', '__setitem__'))
class CompiledProcesses(Processes):
    
    _cache = {}
    
    def __new__(cls, processes):
        """
        Create a ``CompiledProcesses`` object that contains ``Process`` objects as attributes.

        Parameters
        ----------
        processes : Iterable[``Process``]

        Examples
        --------
        None.

        """
        cache = cls._cache
        processes = tuple(processes)
        if processes in cache:
            self = cache[processes]
        else:
            self = object.__new__(cls)
            setfield = setattr
            for i in processes:
                setfield(self, i.ID, i)
            self._compile()
            cache[processes] = self
        return self

    # def __dir__(self):
    #     pass
    
    def compile(self):
        """Do nothing, ``CompiledProcesses`` objects are already compiled."""
        pass
    
    def _compile(self):
        isa = isinstance
        dct = self.__dict__
        tuple_ = tuple # this speeds up the code
        processes = tuple_(dct.values())
        IDs = tuple_([i.ID for i in processes])
        size = len(IDs)
        index = tuple_(range(size))
        dct['tuple'] = processes
        dct['size'] = size
        dct['IDs'] = IDs
        dct['_index'] = index = dict(zip(IDs, index))
        cmps = Components([cmp for i in processes for cmp in i._components])
        cmps.compile()
        dct['_components'] = cmps
        M_stch = []
        params = {}
        rate_eqs = tuple_([i._rate_equation for i in processes])
        all_numeric = True
        for i in processes:
            stch = [0]*cmps.size
            params.update(i._parameters)
            if all_numeric and isa(i._stoichiometry, (list, tuple)): all_numeric = False
            for cmp, coeff in i.stoichiometry.items():
                stch[cmps._index[cmp]] = coeff
            M_stch.append(stch)
        dct['_parameters'] = params
        if all_numeric: M_stch = np.asarray(M_stch)
        dct['_stoichiometry'] = M_stch
        dct['_rate_equations'] = rate_eqs
        dct['_production_rates'] = Matrix(M_stch).T * Matrix(rate_eqs)
        
    @property
    def parameters(self):
        '''[tuple] All symbolic stoichiometric and kinetic parameters.'''
        return tuple(sorted(self._parameters))
    
    @property
    def stoichiometry(self):
        '''[pandas.DataFrame] Stoichiometric coefficients.'''
        return pd.DataFrame(self._stoichiometry, index=self.IDs, columns=self._components.IDs)
    
    @property
    def rate_equations(self):
        '''[pandas.DataFrame] Rate equations.'''
        return pd.DataFrame(self._rate_equations, index=self.IDs, columns=('rate_equation',))
        
    @property
    def production_rates(self):
        '''[pandas.DataFrame] The rates of production of the components.'''
        return pd.DataFrame(list(self._production_rates), index=self._components.IDs, columns=('rate_of_production',))
    
    def subgroup(self, IDs):
        '''Create a new subgroup of ``CompiledProcesses`` objects.'''
        processes = self[IDs]
        new = Processes(processes)
        new.compile()
        return new
    
    def index(self, ID):
        '''Return index of specified process.'''
        try: return self._index[ID]
        except KeyError:
            raise UndefinedProcess(ID)

    def indices(self, IDs):
        '''Return indices of multiple processes.'''
        try:
            dct = self._index
            return [dct[i] for i in IDs]
        except KeyError as key_error:
            raise UndefinedProcess(key_error.args[0])
    
    def __contains__(self, process):
        if isinstance(process, str):
            return process in self.__dict__
        elif isinstance(process, Process):
            return process in self.tuple
        else: # pragma: no cover
            return False
    
    def copy(self):
        '''Return a copy.'''
        copy = Processes(self)
        copy.mycompile()
        return copy    
    