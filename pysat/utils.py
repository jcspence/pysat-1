from __future__ import print_function
from __future__ import absolute_import

import pandas as pds
import numpy as np
import copy
# python 2/3 compatibility
try:
    basestring
except NameError:
    #print ('setting basestring')
    basestring = str

from pysat import DataFrame, Series, datetime, Panel

def computational_form(data):
    """
    Input Series of numbers, Series, or DataFrames repackaged
    for calculation.
    
    Parameters
    ----------
    data : pandas.Series
        Series of numbers, Series, DataFrames

    Returns
    -------
    pandas.Series, DataFrame, or Panel
        repacked data, aligned by indices, ready for calculation
        
    """

    if isinstance(data.iloc[0], DataFrame):
        dslice = Panel.from_dict(dict([(i,data.iloc[i]) for i in xrange(len(data))]))
    elif isinstance(data.iloc[0], Series):
        dslice = DataFrame(data.tolist())
        dslice.index = data.index
    else:
        dslice = data
    return dslice

def set_data_dir(path=None, store=None):
    """
    Set the top level directory pysat uses to look for data and reload.
    
    Parameters
    ----------
    path : string
        valid path to directory pysat uses to look for data
    store : bool
        if True, store data directory for future runs
        
        
    """
    import sys
    import os
    import pysat
    if sys.version_info[0] >= 3:
        if sys.version_info[1] < 4:
            import imp
            re_load = imp.reload
        else:
            import importlib
            re_load = importlib.reload
    else:
        re_load = reload
    if store is None:
        store = True    
    if os.path.isdir(path):
        if store:
            with open(os.path.join(os.path.expanduser('~'), '.pysat', 'data_path.txt'), 'w') as f:
                f.write(path)
        pysat.data_dir = path
        pysat._files = re_load(pysat._files)
        pysat._instrument = re_load(pysat._instrument)
    else:
        raise ValueError('Path does not lead to a valid directory.')
        

def load_netcdf4(fnames=None, strict_meta=False, format=None, time_name='epoch'): #, index_label=None,
                    # unix_time=False, **kwargs):
    """Load netCDF-3/4 file produced by pysat.
    
    Parameters
    ----------
    fnames : string or array_like of strings
        filenames to load
    strict_meta : boolean
        check if metadata across fnames is the same
    format : string
        format keyword passed to netCDF4 routine
        NETCDF3_CLASSIC, NETCDF3_64BIT, NETCDF4_CLASSIC, and NETCDF4
     
    """
                    
    import netCDF4
    import string
    import pysat

    if fnames is None:
        raise ValueError("Must supply a filename/list of filenames")
    if isinstance(fnames, basestring): 
        fnames = [fnames]

    if format is None:
        format = 'NETCDF4'
    else:
        format = format.upper()

    saved_mdata = None
    running_idx = 0
    running_store=[]
    two_d_keys = []; two_d_dims = [];
    for fname in fnames:
        with netCDF4.Dataset(fname, mode='r', format=format) as data:
            # build up dictionary with all global ncattrs
            # and add those attributes to a pysat meta object
            ncattrsList = data.ncattrs()
            mdata = pysat.Meta()
            for d in ncattrsList:
                if hasattr(mdata, d):
                    mdata.__setattr__(d+'_', data.getncattr(d))
                else:
                    mdata.__setattr__(d, data.getncattr(d))
               
            # loadup all of the variables in the netCDF
            loadedVars = {}
            for key in data.variables.keys():
                # load up metadata
                # from here group unique dimensions and act accordingly, 1D, 2D, 3D  
                if len(data.variables[key].dimensions) == 1:
                    # assuming basic time dimension
                    loadedVars[key] = data.variables[key][:] 
                    if key != time_name:
                        # load up metadata
                        meta_dict = {}
                        for nc_key in data.variables[key].ncattrs():
                            meta_dict[nc_key] = data.variables[key].getncattr(nc_key)
                        mdata[key] = meta_dict

                if len(data.variables[key].dimensions) == 2:
                    # part of dataframe within dataframe
                    two_d_keys.append(key)
                    two_d_dims.append(data.variables[key].dimensions)
                    
            # we now have a list of keys that need to go into a dataframe,
            # could be more than one, collect unique dimensions for 2D keys
            for dim in set(two_d_dims):
                # get the name of the final data column
                # dimension naming follows name_dim_number, 
                # pull out name by finding last _ and tracking back
                obj_key_name = dim[1][ : -dim[1][::-1].find('_')-11] #[ : -str.find(dim[1][::-1], '_')-5]
                # collect variable names associated with object
                obj_var_keys = []
                # place to collect clean names without redundant naming scheme scheme
                clean_var_keys = []
                for tkey, tdim in zip(two_d_keys, two_d_dims):
                    if tdim == dim:
                        obj_var_keys.append(tkey)
                        # try to clean variable name based on to_netcdf name mangling
                        # break off leading 'rpa_' from variable name if 
                        # the 2D dimension label (obj_key_name) was 'rpa'
                        clean_var_keys.append(tkey.split(obj_key_name+'_')[-1])

                # figure out how to index this data, it could provide its own
                # index - or we may have to create simple integer based DataFrame access
                # if the dimension is stored as its own variable then use that info for index
                if (obj_key_name+'_dimension_1') in obj_var_keys:
                    # string used to indentify variable in data.variables, will be used as an index 
                    # the obj_key_name part has been stripped off
                    index_key_name = 'dimension_1' #'samples'
                    # if the object index uses UNIX time, process into datetime index  
                    if data.variables[obj_key_name+'_dimension_1'].long_name == 'UNIX time':
                        # name to be used in DataFrame index
                        index_name = 'epoch'
                        time_index_flag = True
                    else:
                        time_index_flag = False
                        # label to be used in DataFrame index
                        index_name = data.variables[obj_key_name+'_dimension_1'].long_name
                else:
                    # dimension is not itself a variable
                    index_key_name  = None                
                              
                # iterate over all of the variables for given dimensions
                # iterate over all variables with this dimension and store data
                # data storage, whole shebang
                loop_dict = {}
                # list holds a series of slices, parsed from dict above
                loop_list = []
                # and pull out metadata
                dim_meta_data = pysat.Meta()
                for key, clean_key in zip(obj_var_keys, clean_var_keys):
                    # data
                    loop_dict[clean_key] = data.variables[key][:,:].flatten(order='C')
                    # store attributes in metadata
                    meta_dict = {}
                    for nc_key in data.variables[key].ncattrs():
                        meta_dict[nc_key] = data.variables[key].getncattr(nc_key)
                    dim_meta_data[clean_key] = meta_dict
                mdata[obj_key_name] = dim_meta_data    
                
                ## iterate over all variables with this dimension and store data
                #loop_list = []
                ## make a dict of all flattened variables
                #loop_dict = {}
                #for key, clean_key in zip(obj_var_keys, clean_var_keys):
                #    loop_dict[clean_key] = data.variables[key][:,:].flatten(order='C')

                # number of values in time
                loop_lim = data.variables[obj_var_keys[0]].shape[0]
                # number of values per time
                step_size = len(data.variables[obj_var_keys[0]][0,:])
                # check if there is an index we should use
                if not (index_key_name is None):
                    # an index was found
                    time_var = loop_dict.pop(index_key_name)
                    if time_index_flag:
                        # create datetime index from data
                        if format == 'NETCDF4':
                            time_var = pds.to_datetime(1E3*time_var)
                        else:
                            time_var = pds.to_datetime(1E6*time_var)
                    new_index = time_var
                    new_index_name = index_name
                else:
                    # using integer indexing
                    new_index = np.arange(loop_lim*step_size) % step_size
                    new_index_name = 'index'
                # load all data into frame
                loop_frame = pds.DataFrame(loop_dict, columns=clean_var_keys)
                # print (loop_frame.columns)
                del loop_frame['dimension_1']
                # break massive frame into bunch of smaller frames
                for i in np.arange(loop_lim):
                    loop_list.append(loop_frame.iloc[step_size*i:step_size*(i+1),:])
                    loop_list[-1].index = new_index[step_size*i:step_size*(i+1)]
                    loop_list[-1].index.name = new_index_name
                        
                # add 2D object data, all based on a unique dimension within netCDF,
                # to loaded data dictionary
                loadedVars[obj_key_name] = loop_list
                del loop_list
                
            # prepare dataframe index for this netcdf file
            time_var = loadedVars.pop(time_name)

            # convert from GPS seconds to seconds used in pandas (unix time, no leap)
            #time_var = convert_gps_to_unix_seconds(time_var)
            if format == 'NETCDF4':
                loadedVars[time_name] = pds.to_datetime((1E3*time_var).astype(int))
            else:
                loadedVars[time_name] = pds.to_datetime((time_var*1E6).astype(int))
            #loadedVars[time_name] = pds.to_datetime((time_var*1E6).astype(int))
            
            running_store.append(loadedVars)
            running_idx += len(loadedVars[time_name])

            if strict_meta:
                if saved_mdata is None:
                    saved_mdata = copy.deepcopy(mdata)
                elif (mdata != saved_mdata):
                    raise ValueError('Metadata across filenames is not the same.')
                    
    # combine all of the data loaded across files together
    out = []
    for item in running_store:
        out.append(pds.DataFrame.from_records(item, index=time_name))
    out = pds.concat(out, axis=0)
    return out, mdata        

def getyrdoy(date):
    """Return a tuple of year, day of year for a supplied datetime object."""
    #if date is not None:
    try:
        doy = date.toordinal()-datetime(date.year,1,1).toordinal()+1
    except AttributeError:
        raise AttributeError("Must supply a pandas datetime object or equivalent")
    else:
        return (date.year, doy)


def season_date_range(start, stop, freq='D'):
    """
    Return array of datetime objects using input frequency from start to stop
    
    Supports single datetime object or list, tuple, ndarray of start and 
    stop dates.
    
    freq codes correspond to pandas date_range codes, D daily, M monthly, S secondly
    """
    
    if hasattr(start, '__iter__'):  
        # missing check for datetime
        season = pds.date_range(start[0], stop[0], freq=freq)
        for (sta,stp) in zip(start[1:], stop[1:]):
            season = season.append(pds.date_range(sta, stp, freq=freq))
    else:
        season = pds.date_range(start, stop, freq=freq)
    return season

#determine the median in 1 dimension
def median1D(self, bin_params, bin_label,data_label):

    bins = np.arange(bin_params[0],bin_params[1]+bin_params[2],bin_params[2])
    ans = 0.*bins[0:-1]
    ind = np.digitize(self.data[bin_label], bins)

    for i in xrange(bins.size-1):
        index, = np.where(ind==(i+1))
        if len(index)>0:
            ans[i] = self.data.ix[index, data_label].median()

    return ans


def create_datetime_index(year=None, month=None, day=None, uts=None):
    """Create a timeseries index using supplied year, month, day, and ut in
    seconds.

    Parameters
    ----------
        year : array_like of ints 
        month : array_like of ints or None
        day : array_like of ints
            for day (default) or day of year (use month=None)
        uts : array_like of floats

    Returns
    -------
        Pandas timeseries index.
        
    Note
    ----
    Leap seconds have no meaning here.
        
    """
    # need a timeseries index for storing satellite data in pandas but
    # creating a datetime object for everything is too slow
    # so I calculate the number of nanoseconds elapsed since first sample, 
    # and create timeseries index from that. 
    # Factor of 20 improvement compared to previous method,
    # which itself was an order of magnitude faster than datetime.
 
    #get list of unique year, and month
    if not hasattr(year, '__iter__'):
        raise ValueError('Must provide an iterable for all inputs.')
    if len(year) == 0:
        raise ValueError('Length of array must be larger than 0.')
    year = year.astype(int)
    if month is None:
        month = np.ones(len(year), dtype=int)
    else:
        month = month.astype(int)
        
    if uts is None:
        uts = np.zeros(len(year))
    if day is None:
        day = np.ones(len(year))
    day = day.astype(int)
    # track changes in seconds
    uts_del = uts.copy().astype(float)
    # determine where there are changes in year and month that need to be 
    # accounted for    
    _,idx = np.unique(year*100.+month, return_index=True)
    # create another index array for faster algorithm below
    idx2 = np.hstack((idx,len(year)+1))   
    # computes UTC seconds offset for each unique set of year and month
    for _idx,_idx2 in zip(idx[1:],idx2[2:]):
        temp = (datetime(year[_idx],month[_idx],1) - datetime(year[0],month[0],1))
        uts_del[_idx:_idx2] += temp.total_seconds()

    # add in UTC seconds for days, ignores existence of leap seconds
    uts_del += (day-1)*86400
    # add in seconds since unix epoch to first day
    uts_del += (datetime(year[0],month[0],1)-datetime(1970,1,1) ).total_seconds()
    # going to use routine that defaults to nanseconds for epoch
    uts_del *= 1E9
    return pds.to_datetime(uts_del)
