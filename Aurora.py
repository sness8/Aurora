#Main Aurora python file, runs the webserver and the Aurora client, configs are loaded from extensions directory
import cherrypy
import os
import multiprocessing
import time
import json
import cherrypy
import configparser
import threading
import glob
import importlib
import inspect
import base64
import logging
import board
import neopixel
from shutil import copyfile

from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('webserver/templates'))

class AuroraManager:
    def __init__(self):
        self.config_file = "./config.ini"
        self.config = {} # config dict
        self.extensions = {}

        self.extensions_dir = False 
        self.current_extension = False
        self.current_extension_name = False 
        self.current_extension_meta = False
        self.screenshot_path = False
        self.extension_started = False
        self.loopRunning = False
        self.messages = []
        self.enabled = False
        self.screenshot_b64 = ""
        self.pixel_image_b64 = ""

        #process config file
        self.loadConfig()

        self.neoPixels = neopixel.NeoPixel(board.D18, 999,auto_write=False)

        #populate extensions
        self.populateExtensions()

        #set/load the extension
        self.setCurrentExtension(self.current_extension_name)

        

    def saveConfig(self):
        with open(self.config_file, 'w') as configfile:
            self.config.write(configfile)
        self.loadConfig()

    
    #Load the config file
    def loadConfig(self):
        self.config = configparser.ConfigParser()
        self.config.optionxform = str
        self.config.read(self.config_file)

        #Lets load the enviroment variables
        for key,val in self.config["AURORA"].items():
            os.environ[key] = val

        #Setup extensions dir
        self.extensions_dir = self.config["EXTENSIONS"]["directory"]

        #Set default extension
        self.current_extension_name = self.config["EXTENSIONS"]["current_extension"]

        #set screenshotpath
        self.screenshot_path = self.config["GENERAL"]["screenshot_path"]
    
        #set pixel image path
        self.pixel_image_path = self.config["GENERAL"]["pixel_image_path"]

        #set enabled flag
        self.enabled = self.config.getboolean("GENERAL","enabled")
            
    #Get a particular extension
    def getExtensionClass(self,extension_name,extension_dir):
        module = importlib.import_module(extension_dir + "." + extension_name,package=extension_name)
        importlib.reload(module)   
        x = False
        try:
            extensionClass = getattr(module,extension_name)
            x = extensionClass(self.neoPixels)
            logging.info("Loaded: {} from ./{}/{}.py".format(x.Name,extension_dir,extension_name))
        except Exception as e:
            self.addMessage("Could not load module from ./{}/{}.py error: {}".format(extension_dir,extension_name,str(e)))
            logging.info("Could not load module from ./{}/{}.py error: {}".format(extension_dir,extension_name,str(e)))
            
        return x

    def fetchMeta(self,extension,filename):
        if(extension == False):
            return False
        extension_meta = {}
        extension_meta["Author"] = extension.Author
        extension_meta["Description"] = extension.Description
        extension_meta["Name"] = extension.Name
        extension_meta["FileName"] = filename
        return extension_meta

    #Populate all the extensions from the extensions class
    def populateExtensions(self):
        self.extensions = {}
        extension_dir = self.extensions_dir
        for file in glob.glob("./{}/*.py".format(extension_dir)):
            filename = os.path.splitext(os.path.basename(file))[0]
            
            # Ignore __ files
            if filename.startswith("__"):
                continue
        
            if(filename not in ['exampleExtension','Aurora_Configure']):
                x = self.getExtensionClass(filename,extension_dir)
                if(x != False):
                    extension_meta = self.fetchMeta(x,filename)
                    self.extensions[filename] = extension_meta

    def addMessage(self,msg):
        
        if(msg not in self.messages):
            self.messages.append(msg)

    
    #Get the current extension to be run
    def getCurrentExtension(self):
        os.environ["AURORA_CURRENT_EXTENSION_NAME"] = self.current_extension_name
        current_extension = self.getExtensionClass(self.current_extension_name,self.extensions_dir)
        self.current_extension = current_extension
        return current_extension

    def setCurrentExtension(self,new_current_extension):
        tempExt = self.getExtensionClass(new_current_extension,self.extensions_dir)
        if(tempExt != False):
            
            while self.loopRunning == True:
                #lets wait this out or things get REEAAAL funky
                time.sleep(0.001)
            
            if(self.extension_started == True):
                self.tearDownExtension()
                self.extension_started = False
            
            self.current_extension = tempExt
            self.current_extension_name = new_current_extension

            os.environ["AURORA_CURRENT_EXTENSION_NAME"] = new_current_extension
            self.current_extension_meta = self.fetchMeta(self.current_extension,new_current_extension)
            self.setupExtension()

            if(new_current_extension != "Aurora_Configure"):
                self.config.set('EXTENSIONS','current_extension',self.current_extension_name)
                self.saveConfig()
                self.extension_started = True


    def takeScreenshot(self):
        if(self.current_extension != False):
            self.current_extension.takeScreenShot(self.screenshot_path)
    
    def makePixelImage(self):
        if(self.current_extension != False):
            self.current_extension.makePixelFrame(self.pixel_image_path)

    def setupExtension(self):
        self.current_extension.setup()
        self.extension_started = True
    
    def tearDownExtension(self):
        self.extension_started = False
        self.current_extension.teardown()
        

    def loop(self):
        if(self.enabled == True): #only if the entire thing is enabled
            if(self.extension_started != False): #only loop if the extension is started
                #lets let other processes know we are in the middle of a loop
                self.loopRunning = True
                try:
                    self.current_extension.visualise()
                except Exception as e:
                    self.addMessage("Error in visualise: {}".format(str(e)))
                self.loopRunning = False


class Aurora_Webserver(object):
    def __init__(self,Manager):
        self.manager = Manager

    @cherrypy.expose
    def about(self):
        self.manager.loadConfig()
        
        tmpl = env.get_template('about.html')
        template_variables = {}
        template_variables['extensions_meta'] = self.manager.extensions
        template_variables['current_extension_meta'] = self.manager.current_extension_meta
        template_variables['config'] = {section: dict(self.manager.config[section]) for section in self.manager.config.sections()}
        template_variables["page"] = "about"
        template_variables['msg'] = self.manager.messages
        self.manager.messages = []
        return tmpl.render(template_variables)

    @cherrypy.expose
    def index(self):
        if(self.manager.current_extension_name == "Aurora_Configure"):
            #process config file
            self.manager.loadConfig()
            #set/load the extension
            self.manager.setCurrentExtension(self.manager.current_extension_name)
            self.manager.setupExtension()

        self.manager.populateExtensions()
        tmpl = env.get_template('index.html')

        template_variables = {}

        template_variables['extensions_meta'] = self.manager.extensions
        template_variables['current_extension_meta'] = self.manager.current_extension_meta
        if(self.manager.current_extension != False):
            template_variables['fps'] = self.manager.current_extension.FPS_avg
        else:
             template_variables['fps'] = 0
        template_variables["configured"] = self.manager.config.getboolean('GENERAL', 'configured')
        template_variables["enabled"] = self.manager.config.getboolean('GENERAL', 'enabled')
        template_variables["page"] = "home"
        template_variables['msg'] = self.manager.messages
        self.manager.messages = []
        return tmpl.render(template_variables)
    
    @cherrypy.expose
    def view(self):
        if(self.manager.current_extension_name == "Aurora_Configure"):
            #process config file
            self.manager.loadConfig()
            #set/load the extension
            self.manager.setCurrentExtension(self.manager.current_extension_name)

        self.manager.populateExtensions()
        tmpl = env.get_template('view.html')
        self.screenshot()
        template_variables = {}

        template_variables['extensions_meta'] = self.manager.extensions
        template_variables['current_extension_meta'] = self.manager.current_extension_meta
        if(self.manager.current_extension != False):
            template_variables['fps'] = self.manager.current_extension.FPS_avg
        else:
             template_variables['fps'] = 0
        template_variables["configured"] = self.manager.config.getboolean('GENERAL', 'configured')
        template_variables["enabled"] = self.manager.config.getboolean('GENERAL', 'enabled')
        template_variables["page"] = "view"
        template_variables['msg'] = self.manager.messages
        self.manager.messages = []
        return tmpl.render(template_variables)

    @cherrypy.expose
    def configure(self):
        if(self.manager.enabled == False): #Its turned off, we need it on to config
            self.manager.enabled = True
        tmpl = env.get_template('configure.html')
        self.manager.setCurrentExtension("Aurora_Configure")
        self.manager.extension_started = False #so it doesnt loop visualise
        self.manager.current_extension.visualise()
        template_variables = {}
        template_variables["pixels_left"] = self.manager.current_extension.pixelsLeft
        template_variables["pixels_right"] = self.manager.current_extension.pixelsRight
        template_variables["pixels_top"] = self.manager.current_extension.pixelsTop
        template_variables["pixels_bottom"] =self.manager.current_extension.pixelsBottom
        template_variables["page"] = "configure"
        template_variables['msg'] = self.manager.messages
        self.manager.messages = []
        print("----"*20)
        return tmpl.render(template_variables)


    
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    @cherrypy.expose
    def update_config(self):
        input_json = cherrypy.request.json
        if "enabled" in input_json:
            try:
                return_json = {"status":"ok"}
                enabled_status = input_json["enabled"]
                self.manager.enabled = enabled_status
                if(enabled_status == False):
                    #we are turning it off, tear down the extension
                    self.manager.tearDownExtension()
                    return_json["message"] = "Aurora successfully turned off"
                elif(enabled_status == True):
                    #we are turning it on, lets put everything back
                    self.manager.setupExtension()
                    return_json["message"] = "Aurora successfully turned on"

                self.manager.config.set("GENERAL","enabled",str(enabled_status))
                self.manager.saveConfig()
                return return_json

            except Exception as e:
                return {"status":"error","error":str(e)}
                pass
        else:
            return {"status":"error","error":"No setting found in request"}

    @cherrypy.tools.json_out()
    @cherrypy.tools.json_in()
    @cherrypy.expose
    def update_LED_config(self):
        input_json = cherrypy.request.json
        pixelcount_left = self.manager.current_extension.pixelsLeft
        pixelcount_right = self.manager.current_extension.pixelsRight
        pixelcount_top = self.manager.current_extension.pixelsTop
        pixelcount_bottom = self.manager.current_extension.pixelsBottom
        
        configChange = False
        
        
        errors = []

        if "pixelcount_left" in input_json:
            try:
                led_input_count = int(input_json["pixelcount_left"])
                if(led_input_count != pixelcount_left):
                    configChange = True
                    pixelcount_left = led_input_count
            except Exception as e:
                errors.append(str(e))
                pass #whatever, you are doing bad things with input
            
        if "pixelcount_right" in input_json:
            try:
                led_input_count = int(input_json["pixelcount_right"])
                if(led_input_count != pixelcount_right):
                    configChange = True
                    pixelcount_right = led_input_count
            except Exception as e:
                errors.append(str(e))
                pass #whatever, you are doing bad things with input
        
        if "pixelcount_top" in input_json:
            try:
                led_input_count = int(input_json["pixelcount_top"])
                if(led_input_count != pixelcount_top):
                    configChange = True
                    pixelcount_top = led_input_count
            except Exception as e:
                errors.append(str(e))
                pass #whatever, you are doing bad things with input

        if "pixelcount_bottom" in input_json:
            try:
                led_input_count = int(input_json["pixelcount_bottom"])
                if(led_input_count != pixelcount_bottom):
                    configChange = True
                    pixelcount_bottom = led_input_count
            except Exception as e:
                errors.append(str(e))
                pass #whatever, you are doing bad things with input

        pixelcount_total = pixelcount_left + pixelcount_right + pixelcount_top + pixelcount_bottom
        
        try:
            self.manager.current_extension.pixelsCount  = pixelcount_total
            self.manager.current_extension.pixelsLeft = pixelcount_left
            self.manager.current_extension.pixelsRight = pixelcount_right
            self.manager.current_extension.pixelsTop = pixelcount_top
            self.manager.current_extension.pixelsBottom = pixelcount_bottom
            self.manager.current_extension.setup() 
            self.manager.current_extension.visualise()
        except Exception as e:
                errors.append(str(e))
        
        
        
        if "save" in input_json:
            try:
                self.manager.config.set("AURORA","AURORA_PIXELCOUNT_LEFT",str(pixelcount_left))
                self.manager.config.set("AURORA","AURORA_PIXELCOUNT_RIGHT",str(pixelcount_right))
                self.manager.config.set("AURORA","AURORA_PIXELCOUNT_TOP",str(pixelcount_top))
                self.manager.config.set("AURORA","AURORA_PIXELCOUNT_BOTTOM", str(pixelcount_bottom))
                self.manager.config.set("AURORA","AURORA_PIXELCOUNT_TOTAL", str(pixelcount_total))
                self.manager.config.set("GENERAL","configured", "True")
                self.manager.saveConfig()
                self.manager.addMessage("Saved config!")
            except Exception as e:
                errors.append(str(e))

        if(len(errors) == 0):
            return {"status":"ok"}
        else:
            error_string = ",".join(errors)
            return {"status":"error","error":error_string}
        
        

    @cherrypy.tools.json_out()
    @cherrypy.tools.json_in()
    @cherrypy.expose
    def update_extension(self):
        input_json = cherrypy.request.json
        if "extension_name" in input_json:
            extension_name = input_json["extension_name"]
            self.manager.setCurrentExtension(extension_name)

        return {"status":"ok"}


    @cherrypy.tools.json_out()
    @cherrypy.expose
    def screenshot(self):
        self.manager.takeScreenshot()
        self.manager.makePixelImage()
       
        if(self.manager.current_extension != False):
            return {"status":"ok"}
        else:
            return {"status":"error","error":"Could not take screenshot and build pixel image"}
        
    @cherrypy.expose
    def load_screenshot(self,**params):
        screenshot_path = self.manager.screenshot_path
        print("hdmi state:{}".format(self.manager.current_extension.noHDMI))
        #Its not enabled, it doesnt use HDMI or its got a 1x1 image (ie nothing on)
        if(self.manager.enabled == False or self.manager.current_extension.noHDMI == True or (self.manager.current_extension.vid_h == 1 or self.manager.current_extension.vid_w == 1) ):
            screenshot_path = os.getcwd() + "/webserver/static/img/emptyimage.jpg"
        try:
            f = open(screenshot_path, "rb")
            contents = f.read()
            f.close()
            return contents
        except Exception as e:
            self.manager.log("Error loading image {}: Err: {}".format(self.manager.screenshot_path,str(e)))
            return False
    
    @cherrypy.expose
    def load_pixel_image(self,**params):
        try:
            f = open(self.manager.pixel_image_path, "rb")
            contents = f.read()
            f.close()
            return contents
        except Exception as e:
            self.manager.log("Error loading image {}: Err: {}".format(self.manager.pixel_image_path,str(e)))
            return False

if __name__ == '__main__':
    
    AuroraManager = AuroraManager()
    
    if(AuroraManager.config.getboolean('WEBSERVER', 'enabled') == True):
        
        conf = {
            '/': {
                'tools.sessions.on': True,
                'tools.staticdir.root': os.path.abspath(os.getcwd())
            },
            '/assets': {
                'tools.staticdir.on': True,
                'tools.staticdir.dir': './webserver/static'
            }
        }
        
        cherrypy.config.update({'log.screen': False,
                        'log.access_file': '',
                        'log.error_file': ''})    
        cherrypy.config.update({'server.socket_port': AuroraManager.config.getint('WEBSERVER','server_port')})
        cherrypy.config.update({'server.socket_host': AuroraManager.config.get('WEBSERVER','listen_host')})
        cherrypy.config.update({'engine.autoreload.on':False })
        
        cherrypy.tree.mount(Aurora_Webserver(AuroraManager), '/',conf)
        cherrypy.engine.start()
    
    while(True):
        AuroraManager.loop()
        time.sleep(0.001)

    '''
    currentExtensionName = os.environ["AURORA_CURRENT_EXTENSION"]
    currentExtension = loadCurrentExtension(currentExtensionName)

    while(True):
        print("{}".format(os.environ["AURORA_CURRENT_EXTENSION"]))
        if(os.environ["AURORA_CURRENT_EXTENSION"] != currentExtensionName):
            #we changed to a diff thing
            print("WOW IT CHANGED")
            currentExtensionName = os.environ["AURORA_CURRENT_EXTENSION"]
            currentExtension = loadCurrentExtension(currentExtensionName)

        currentExtension.visualise()
    ''' 
    # do other work

   