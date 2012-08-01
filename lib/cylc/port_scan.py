#!/usr/bin/pyro

#C: THIS FILE IS PART OF THE CYLC FORECAST SUITE METASCHEDULER.
#C: Copyright (C) 2008-2012 Hilary Oliver, NIWA
#C:
#C: This program is free software: you can redistribute it and/or modify
#C: it under the terms of the GNU General Public License as published by
#C: the Free Software Foundation, either version 3 of the License, or
#C: (at your option) any later version.
#C:
#C: This program is distributed in the hope that it will be useful,
#C: but WITHOUT ANY WARRANTY; without even the implied warranty of
#C: MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#C: GNU General Public License for more details.
#C:
#C: You should have received a copy of the GNU General Public License
#C: along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os, sys
from hostname import hostname
from owner import user
from passphrase import passphrase
from registration import localdb
import Pyro.errors, Pyro.core
from conf.CylcGlobals import pyro_base_port, pyro_port_range

class SuiteIdentificationError( Exception ):
    """
    Attributes: None
    """
    def __init__( self, msg ):
        self.msg = msg
    def __str__( self ):
        return repr(self.msg)

class ConnectionDeniedError( SuiteIdentificationError ):
    pass

class ConnectionTimedOutError( SuiteIdentificationError ):
    pass

class NoSuiteFoundError( SuiteIdentificationError ):
    pass

class SuiteNotFoundError( SuiteIdentificationError ):
    pass

class OtherSuiteFoundError( SuiteIdentificationError ):
    pass

class OtherServerFoundError( SuiteIdentificationError ):
    pass

class port_interrogator(object):
    # find which suite or lockserver is running on a given port
    def __init__( self, host, port, my_passphrases=None, timeout=None ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.my_passphrases = my_passphrases

    def interrogate( self ):
        # get a proxy to the cylcid object
        # this raises ProtocolError if connection fails
        uri = 'PYROLOC://' + self.host + ':' + str(self.port) + '/cylcid' 
        self.proxy = Pyro.core.getProxyForURI(uri)
        self.proxy._setTimeout(self.timeout)

        # first try access with no passphrase
        name = owner = None
        try:
            # (caller handles TimeoutError)
            name, owner = self.proxy.id()
        except Pyro.errors.ConnectionDeniedError, x:
            # must be a secure suite, try my passphrases
            if not self.my_passphrases:
                raise
            for reg in self.my_passphrases:
                self.proxy._setIdentification( self.my_passphrases[reg] )
                try:
                    name, owner = self.proxy.id()
                except:
                    # denied, try next passphrase
                    continue
                else:
                    # got access
                    if name == reg and owner == user:
                        return name, owner, 'secure'
                    else:
                        # this indicates that one of my suites has an
                        # identical passphrase to this other suite.
                        continue

            # loop end without returning ID => all of my passphrases denied
            raise Pyro.errors.ConnectionDeniedError, x
        except:
            raise
        else:
            # got access with no passphrase => not a secure suite
            return name, owner, 'insecure'

def warn_timeout( host, port, timeout ):
    print >> sys.stderr, "WARNING: connection timed out (" + str(timeout) + "s) at", portid( host, port )
    print >> sys.stderr, '  This could mean a Ctrl-Z stopped suite or similar is holding up the port,'
    print >> sys.stderr, '  or your cylc connection timeout needs to be longer than', str(timeout), 'seconds.'

def portid( host, port ):
    return host + ":" + str(port)

# old complex output format for scan command etc.: '[suite] owner@host:port'
# new simple output format is: 'suite owner host port' - better for parsing.
##def suiteid( name, owner, host, port=None ):
##    if port != None:
##        res = "[" + name + "] " + owner + "@" + portid( host,port)
##    else:
##        res = "[" + name + "] " + owner + "@" + host
##    return res

def cylcid_uri( host, port ):
    return 'PYROLOC://' + host + ':' + str(port) + '/cylcid' 

def get_port( suite, owner=user, host=hostname, pphrase=None, timeout=1.0, silent=False ):
    # Scan ports until a particular suite is found.

    for port in range( pyro_base_port, pyro_base_port + pyro_port_range ):
        uri = cylcid_uri( host, port )
        try:
            proxy = Pyro.core.getProxyForURI(uri)
        except Pyro.errors.URIError, x:
            # No such host?
            raise SuiteNotFoundError, x

        proxy._setTimeout(timeout)
        proxy._setIdentification( pphrase )

        try:
            name, xowner = proxy.id()
        except Pyro.errors.TimeoutError:
            warn_timeout( host, port, timeout )
            pass
        except Pyro.errors.ConnectionDeniedError:
            #print >> sys.stderr, "Wrong suite or wrong passphrase at " + portid( host, port )
            pass
        except Pyro.errors.ProtocolError:
            #print >> sys.stderr, "No Suite Found at " + portid( host, port )
            pass
        except Pyro.errors.NamingError:
            #print >> sys.stderr, "Non-cylc pyro server found at " + portid( host, port )
            pass
        else:
            if name == suite and xowner == owner:
                if not silent:
                    print suite, owner, host, port
                # RESULT
                return port
            else:
                # ID'd some other suite.
                #print 'OTHER SUITE:', name, xowner, host, port
                pass
    raise SuiteNotFoundError, "Suite not running: " + suite + ' ' + owner + ' ' + host

def check_port( suite, pphrase, port, owner=user, host=hostname, timeout=1.0, silent=False ):
    # is a particular suite running at host:port?

    uri = cylcid_uri( host, port )
    proxy = Pyro.core.getProxyForURI(uri)
    proxy._setTimeout(timeout)
    # note: we'll get a TimeoutError if the connection times out

    # Giving the suite passphrase does not result in connection
    # denied if the suite is currently not using its passphrase
    proxy._setIdentification( pphrase )

    try:
        name, xowner = proxy.id()
    except Pyro.errors.TimeoutError:
        warn_timeout( host, port, timeout )
        raise ConnectionTimedOutError, "ERROR, Connection Timed Out " + portid( host, port )
    except Pyro.errors.ConnectionDeniedError:
        raise ConnectionDeniedError, "ERROR: Connection Denied  at " + portid( host, port )
    except Pyro.errors.ProtocolError:
        raise NoSuiteFoundError, "ERROR: " + suite + " not found at " + portid( host, port )
    except Pyro.errors.NamingError:
        raise OtherServerFoundError, "ERROR: non-cylc pyro server found at " + portid( host, port )
    else:
        if name == suite and xowner == owner:
            # RESULT
            if not silent:
                print suite, owner, host, port
            return True
        else:
            # ID'd some other suite.
            print >> sys.stderr, 'Found ' + name + ' ' + xowner + ' ' + host + ' ' + port
            print >> sys.stderr, ' NOT ' + suite + ' ' + owner + ' ' + host + ' ' + port
            raise OtherSuiteFoundError, "ERROR: Found another suite"

def scan( host=hostname, verbose=True, mine=False, silent=False, db=None, timeout=1.0 ):
    #print 'SCANNING PORTS'
    # scan all cylc Pyro ports for cylc suites

    # load my suite passphrases 
    reg = localdb(db)
    reg.load_from_file()
    reg_suites = reg.get_list()
    my_passphrases = {}
    for item in reg_suites:
        rg = item[0]
        di = item[1]
        try:
            pp = passphrase( rg, user, host ).get( suitedir=di )
        except Exception, x:
            #print >> sys.stderr, x
            # no passphrase defined for this suite
            pass
        else:
            my_passphrases[ rg ] = pp

    suites = []
    for port in range( pyro_base_port, pyro_base_port + pyro_port_range ):
        try:
            name, owner, security = port_interrogator( host, port, my_passphrases, timeout ).interrogate()
        except Pyro.errors.TimeoutError:
            warn_timeout( host, port, timeout )
            pass
        except Pyro.errors.ConnectionDeniedError:
            # secure suite
            if not silent:
                print >> sys.stderr, "Connection Denied at " + portid( host, port )
        except Pyro.errors.ProtocolError:
            # no suite
            #if not silent:
            #    print >> sys.stderr, "No Suite Found at " + portid( host, port )
            pass
        except Pyro.errors.NamingError:
            # other Pyro server
            if not silent:
                print >> sys.stderr, "Non-cylc Pyro server found at " + portid( host, port )
        except:
            raise
        else:
            if verbose:
                if not silent:
                    print name, owner, host, port
            # found a cylc suite or lock server
            if mine:
                if owner == user:
                    suites.append( ( name, port ) )
            else:
                suites.append( ( name, owner, port ) )
    return suites

