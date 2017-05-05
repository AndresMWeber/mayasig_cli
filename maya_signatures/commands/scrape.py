# maya_signatures/commands/scrape.py
"""The maya online help command signature scraping command."""

from six import iteritems
import requests
import tempfile
import json
import shutil
import os
from .base import Base
from .cache import KeyMemoized
from bs4 import BeautifulSoup


class Scrape(Base):
    BASEURL = 'http://help.autodesk.com/cloudhelp/{MAYAVERSION}/ENU/Maya-Tech-Docs/CommandsPython/'
    _EXTENSION = 'html'
    _URL_BUILDER = '{BASEURL}{COMMAND}.{EXT}'
    _CACHE_FILE = '%s.json' % __name__.split('.')[-1]

    def __init__(self, *args, **kwargs):
        super(Scrape, self).__init__(*args, **kwargs)
        self.depth = self.kwargs.get('--depth', 1)
        self.maya_version = self.kwargs.get('--mayaversion', ['2017'])[0]
        self.command_signatures = {}
        self.run()

    @property
    def cache_file(self):
        """ Provides the cache file path
        
        - **parameters**, **types**, **return**::
            :return: str
        """
        return os.path.join(os.getcwd(), self._CACHE_FILE)

    @property
    def cached(self):
        """ Provides the raw cache with urls as the dictionary keys
        
        - **parameters**, **types**, **return**::    
            :return: dict
        """
        return self.scrape_command.cache

    @property
    def stored_commands(self):
        """ Provides a list of commands that are currently stored.
        
        - **parameters**, **types**, **return**::
            :return: list
        """
        return list(self.command_signatures)

    def run(self):
        """ CLI interface command runner
        
        - **parameters**, **types**, **return**::
            :return: dict, command signatures dictionary sorted the commands as the keys 
        """
        commands = self.kwargs.get('MAYA_CMDS', [])
        self._read_tempfile()
        self._store_commands(commands)
        self._write_tempfile()
        return self.command_signatures

    @KeyMemoized
    def scrape_command(self, maya_command_url):
        """ Actual worker command which parses the Maya online help docs for the given command URL
        
        - **parameters**, **types**, **return**::
            :return: dict(str:dict(str:str, str:str, str:str), dict with keys of flags and each flag value is a dict
                     of short name 'short', data type 'data_type' and description 'description'
        """
        print('Trying to find command for web page: \n\t%s' % maya_command_url)
        web_page_data = requests.get(maya_command_url)
        soup_data = BeautifulSoup(web_page_data.content, 'html.parser')

        raw_flag_table = self._parse_flag_table(soup_data)
        flags = self._compile_flag_table(raw_flag_table)
        return flags

    def reset_cache(self):
        """ Clears the cache file of contents.
        
        - **parameters**, **types**, **return**::
            :return: None
        """
        open(self._CACHE_FILE, 'w').close()

    def get_command_flags(self, command):
        """ Returns only the flags for the given command
        
        - **parameters**, **types**, **return**::
            :param command: str, maya command
            :return: list(list(str, str)), list of lists of flags in format: [<long name>, <short name>]
        """
        return zip(list(self.command_signatures[command]),
                   [self.command_signatures[command][flag]['short'] for flag in self.command_signatures[command]])

    def build_command_stub(self, command, shortname=False, combined=False):
        """ Builds a Python stub for the given command.
        
        - **parameters**, **types**, **return**::
            :param command: str, valid maya command
            :param shortname: bool, whether or not we want to use the shortname of the flags
            :param combined: bool, whether we use both short name and long name of flags (will invalidate stub...)
            :return: str, Python formatted function stub for the given command
        """
        lut = {'boolean': 'bool', 'string': 'str', 'int': 'int'}
        kwargs = []
        shortname = False if combined else shortname

        for k, v in iteritems(self.command_signatures[command]):
            flag = k if not shortname else v['short']
            if combined:
                flag += '(%s)' % v['short']
            kwargs.append('{FLAG}={TYPE}'.format(FLAG=flag, TYPE=lut[v['data_type']]))
        signature = ', '.join(kwargs)
        return 'def {CMD}(*args, {SIG}):\n\tpass'.format(CMD=command, SIG=signature)

    def _read_tempfile(self):
        """ Attempts to read and store instance data from the cache file
            :return: None
        """
        try:
            with open(self._CACHE_FILE, ) as data_file:
                try:
                    data = json.load(data_file)
                except ValueError:
                    data = {}
            print('Successfully loaded json data, loading into cache...')
            self.scrape_command.cache = data
        except IOError:
            print('No preexisting scrape.json detected in folder %s continuing...' % self.cache_file)

    def _build_url(self, command):
        """ Uses class variables to synthesize a URL path to the maya help lib for the given command
            :param command: str, valid maya command
            :return: str, url to the maya help lib for given command.
        """
        return self._URL_BUILDER.format(BASEURL=self.BASEURL.format(MAYAVERSION=self.maya_version),
                                        COMMAND=command,
                                        EXT=self._EXTENSION)

    def _store_commands(self, commands):
        """ Builds URLs then stores all queried commands within the instance
            :param commands: list(str) or str, valid maya command(s)
            :return: None
        """
        if isinstance(commands, (str, unicode)):
            commands = [commands]

        for maya_command in commands:
            url = self._build_url(maya_command)
            self.command_signatures[maya_command] = self.scrape_command(self, url)

    def _write_tempfile(self):
        """ Writes instance data to the cache file
            :return: None
        """
        f = tempfile.NamedTemporaryFile(mode='w+t', delete=False)
        f.write(json.dumps(self.scrape_command.cache, ensure_ascii=False, indent=4, sort_keys=True))
        file_name = f.name
        f.close()
        shutil.copy(file_name, self._CACHE_FILE)
        print("wrote out tmp file %s" % self.cache_file)

    @classmethod
    def _parse_synopsis(cls, soup_code_object):
        """ Parses the webpage for the synopsis value
            :param soup_code_object: str, return of beautiful soup for maya help doc page
            :return: list(str): list of synopsis values (should be the flags)
        """
        synopses = []
        for child in [child for child in soup_code_object.children]:
            synopses.append(unicode(child) if not hasattr(child, 'string') else child.string)
        return synopses

    @classmethod
    def _parse_flag_table(cls, soup_code_object):
        """ Parses (naively) the webpage for the flag table
            :param soup_code_object: str, return of beautiful soup for maya help doc page
            :return: list(list(str, str, str, str)): list of lists len 4 of:
                        flag name, short name, data type, description
        """
        signature_table = [table for table in soup_code_object.body.find_all('table')
                           if 'Long name (short name)' in unicode(table.find_all('tr'))][0]

        data = []
        for table_row in signature_table.find_all('td'):
            # This is a ghetto way of checking whether it's the right row we want...but it works.
            if table_row.attrs.get('colspan') is None:
                text = str(table_row.text.strip()).replace('\n', ' ')
                # Might need refactoring later depending on how they format their flags/descriptions, but we'll see
                if len(text.split('(')) == 2 and not ' ' in text:
                    text = [t.replace(')', '') for t in text.split('(')]
                    data += text
                elif text:
                    data.append(text)

        return [data[x:x + 4] for x in range(0, len(data), 4)]

    @staticmethod
    def _compile_flag_table(flag_data_set):
        """ Parses Takes the parsed data set from Scrape.parse_flag_table and creates a dictionary
            :param flag_data_set: list(list(str, str, str, str)): list of lists len 4 of:
                                    flag name, short name, data type, description
            :return: dict(str:dict(str:str, str:str, str:str), dict with keys of flags and each flag value is a dict
                     of short name 'short', data type 'data_type' and description 'description'
        """
        flags = {}
        for flag_data in flag_data_set:
            name, short, data_type, description = flag_data
            flags[name] = {'short': short, 'data_type': data_type, 'description': description}

        return flags
