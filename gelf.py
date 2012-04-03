#from gelf import g_interface, g_engine
import threading, sys, signal, time, Queue
import os

import cherrypy

from ws4py.server.cherrypyserver import WebSocketPlugin, WebSocketTool
from ws4py.websocket import WebSocket
from ws4py.messaging import TextMessage

import subprocess
#import cherrypy

class G_Web(object):
	def __init__(self, engine):
		self.eng = engine
		pass
	
	@cherrypy.expose
	def ws(self):
		cherrypy.log("Handler created: %s" % repr(cherrypy.request.ws_handler))
	
	@cherrypy.expose
	def index(self):
		"""
		HTML for web relay, including JS to run the WS, maybe some stats/metrics features.
		"""
		self.scheme = "ws" #wss for ssl support 
		self.host = "localhost" #changeme
		self.port = 9000 #changeme
		page = """<html>
    <head>
      <script type='application/javascript' src='/js/jquery-1.6.2.min.js'></script>
      <script type='application/javascript'>
        $(document).ready(function() {

          websocket = '%(scheme)s://%(host)s:%(port)s/ws';
          if (window.WebSocket) {
            ws = new WebSocket(websocket);
          }
          else if (window.MozWebSocket) {
            ws = MozWebSocket(websocket);
          }
          else {
            console.log('WebSocket Not Supported');
            return;
          }

          window.onbeforeunload = function(e) {
            $('#chat').val($('#chat').val() + 'Bye bye...\\n');
            ws.close(1000, 'fake left the room');
                 
            if(!e) e = window.event;
            e.stopPropagation();
            e.preventDefault();
          };
          ws.onmessage = function (evt) {
             $('#chat').val($('#chat').val() + evt.data + '\\n');
          };
          ws.onopen = function() {
             ws.send("fake entered the room");
          };
          ws.onclose = function(evt) {
             $('#chat').val($('#chat').val() + 'Connection closed by server: ' + evt.code + ' \"' + evt.reason + '\"\\n');  
          };

          $('#send').click(function() {
             console.log($('#message').val());
             ws.send('fake: ' + $('#message').val());
             $('#message').val("");
             return false;
          });
        });
      </script>
    </head>
    <body>
    <form action='#' id='chatform' method='get'>
      <textarea id='chat' cols='35' rows='10'></textarea>
      <br />
      <label for='message'>fake: </label><input type='text' id='message' />
      <input id='send' type='submit' value='Send' />
      </form>
    </body>
    </html>
    """ % {'host': self.host, 'port': self.port, 'scheme': self.scheme}
		while self.eng.outgoing.empty() == False:
			page += self.eng.get_outgoing().layer3.encode("hex")
		return page

class G_Web_WS(WebSocket):
	def received_message(self, m):
		"""
		Web server sends data to incoming queue
		"""
		cherrypy.engine.publish('websocket-broadcast', m)

	def closed(self, code, reason="closed"):
		"""
		Client disconnects from relay
		"""
		cherrypy.engine.publish('websocket-broadcast', TextMessage(reason))

class Packet():
	ether = None
	layer3 = None

class G_Engine():
	outgoing = Queue.Queue()
	incoming = Queue.Queue()
	
	def put_outgoing(self, packet):
		self.outgoing.put(packet)
		pass
	
	def get_outgoing(self):
		packet = self.outgoing.get()
		self.outgoing.task_done()
		return packet
	
	def put_incoming(self, packet):
		self.incoming.put(packet)
		pass
	
	def get_incoming(self):
		packet = self.incoming.get()
		self.incoming.task_done()
		return packet

class G_Interface():
	def __init__(self, dev):
		"""
		Open interface dev for reading, in this example we use a tun0
		
		Args:
			dev: the interface to read/write from
		"""
		self.mtu = 1500
		self.fd = None
		
		if True:
			self.osx_create_tap(dev)
		
	
	def osx_create_tap(self, dev):
		"""
		If the target OS is OSX, we create a tap device by opening it R/W.
		We cannot read input/output until the device is configured.
		
		Args:
			dev: the device (tapX) to be configured.
		"""
		if not os.path.exists("/dev/%s" % dev):
			print "[G_Interface//Error]: Device %s does not exist" % dev
		try:
			self.fd = os.open("/dev/%s" % dev, os.O_RDWR)
		except OSError as e:
			print "[G_Interface//Error]:", e
			sys.exit(1)
		subprocess.call(["ifconfig", dev, "up"])
		
		
	def read(self):
		"""
		Read data from the configured interface.
		This function should be replaced with a call to a scapy/pickel reader.
		"""
		
		packet = Packet()
		read_buffer = None
		try:
			read_buffer = os.read(self.fd, self.mtu)
			packet.ether = read_buffer[:14]
			packet.layer3 = read_buffer[14:]
		except OSError as e:
			print "[G_Interface//Error]:", e
			sys.exit(1)
		'''Separate the layer2/3 data for future decision on whether to use/forward layer2 information'''
		return packet
	
	def write(self, packet):
		"""
		Write layer 3 data to interface
		"""
		write_status = -1
		try:
			write_status = os.write(self.fd, packet.layer3)
		except OSError as e:
			print e
			sys.exit(1)
		return write_status

class T_IO(threading.Thread):
	interface = None
	engine = None
	def __init__(self, g_int, g_eng, ws):
		threading.Thread.__init__(self)
		self.interface = g_int
		self.engine = g_eng
		self.kill_received = False
		self.ws = ws

class T_Outgoing(T_IO):
	def __init__(self, g_int, g_eng, ws):
		T_IO.__init__(self, g_int, g_eng, ws)
		
	def run(self):
		"""
		Read from g_int.read() and write to g_eng.outgoing
		"""
	
		print "[T_Outgoing//Notice]: Running"
		
		#Testing
		# Read binary data into out_buffer	
		packet = Packet()
		#while True:
		while not self.kill_received: # debuggin
			packet = self.interface.read()
			if packet.ether is None:
				continue
			print "[T_Outgoing//Debug]: Read packet", packet.layer3.encode("hex")
			'''Todo: obtain mutext on g_eng.outgoing'''
			#self.engine.put_outgoing(packet)
			#time.sleep(0)
			"""Hack, write directly to the WS"""
			ws.broadcast(TextMessage(packet.layer3.encode("hex")))

class T_Incoming(T_IO):
	def __init__(self, g_int, g_eng, ws):
		T_IO.__init__(self, g_int, g_eng, ws)	
		
	def run(self):
		"""
		Read from g_int.read() and write to g_eng.outgoing
		"""
	
		# Read binary data into out_buffer	
		out_buffer =""
		while not self.kill_received:
			out_buffer = self.interface.read()
			'''Todo: obtain mutext on g_eng.outgoing'''
			self.engine.add_outgoing(out_buffer)	

def start_threads(g_int, g_eng, ws):
	threads = []
	t = T_Outgoing(g_int, g_eng, ws)
	threads.append(t)
	threads[-1].start()
	return threads

def join_threads(threads):
	for t in threads:
		t.join()
	
def joiner(signum, frame):
	print "Caught signal:", signum
	join_threads()
	sys.exit() 

if __name__ == "__main__":
	# Enable websocket plugin for cherrypy
	ws = WebSocketPlugin(cherrypy.engine)

	# Create Queue managers
	engine = G_Engine(ws)
	# Start read/write interface
	interface = G_Interface("tap0")
	# Instanciate web handler
	web = G_Web()

	# Start read/write threads
	threads = start_threads(interface, engine, ws)

	# Cherrypy configurations
	cherrypy.config.update({
		"server.socket_host": "127.0.0.1",
		"server.socket_port": 9000,
		"tools.staticdir.root": os.path.abspath(os.path.join(os.path.dirname(__file__), 'static'))
	})
	ws.subscribe()
	cherrypy.tools.websocket = WebSocketTool()

	# Set websocket url, and static js directory	
	cherrypy.quickstart(web, '', config={
		"/ws": {
			'tools.websocket.on': True,
			'tools.websocket.handler_cls': G_Web_WS
		},
		"/js": {
			"tools.staticdir.on": True,
			"tools.staticdir.dir": "js"
		}
	})
	
	# Debugging
	while len(threads) > 0:
		try:
			threads = [t.join(1) for t in threads if t is not None and t.isAlive()]
		except KeyboardInterrupt:
			print "[Main//Debug]: Killing I/O threads"
			for t in threads:
				t.kill_received = True
	#join_threads(threads)
	#cherrypy.quickstart(g_web)


