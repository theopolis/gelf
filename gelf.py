import argparse
import threading, sys
import os
import time
import struct

import cherrypy

from ws4py.server.cherrypyserver import WebSocketPlugin, WebSocketTool
from ws4py.websocket import WebSocket
from ws4py.messaging import BinaryMessage

from ws4py.client.threadedclient import WebSocketClient

class GelfRelay(object):
	def __init__(self, host, port):
		self.host = host
		self.port = port
		self.scheme = 'ws'
		pass
	
	@cherrypy.expose
	def ws(self):
		cherrypy.log("Handler created: %s" % repr(cherrypy.request.ws_handler))
	
	@cherrypy.expose
	def index(self, name=None):
		"""
		HTML for web relay, including JS to run the WS, maybe some stats/metrics features.
		"""
		page = """<html>
    <head>
      <script type='application/javascript' src='/js/jquery-1.6.2.min.js'></script>
      <script type='application/javascript' src='/js/gelf.js'></script>
      <script type='application/javascript'>
      	$(document).ready(function() { gelf.main('%(host)s', '%(port)s');} );
      </script>
    </head>
    <body>
    <form action='#' id='relayform' method='get'>
      <textarea id='log' cols='70' rows='30'></textarea>
      <br />
      <label for='message'>new: </label><input type='text' id='host' /> <input type='text' id='port' />
      <input id='add' type='button' value='Add' />
      </form>
    </body>
    </html>
    """ % {'host': self.host, 'port': self.port, 'scheme': self.scheme}
		return page

class GelfWebSocketHandler(WebSocket):
	def received_message(self, m):
		"""
		Web server sends data to incoming queue
		"""
		cherrypy.engine.publish('websocket-broadcast', m)

	def closed(self, code, reason="closed"):
		"""
		Client disconnects from relay
		"""
		cherrypy.engine.publish('websocket-broadcast', BinaryMessage(reason))

class GelfInterface():
	def __init__(self, hw_port="", use_header=False, mtu=1500):
		"""
		Open interface dev for reading, in this example we use a tun0
		
		Args:
			dev: the interface to read/write from
		"""
		self.mtu = mtu
		self.fd = None
		self.hw_port = hw_port
		self.use_header = use_header
		
		self.open_tap()
	
	def darwin_init_interface(self):
		path = None
		for i in range(15):
			try:
				path = "tap%d" % i
				self.fd = os.open(os.path.join("/dev/", path), os.O_RDWR)
				break
			except: #OSError as e
				path = None
				self.fd = None
		if self.fd == None:
			print "[GelfInterface//Error]: Could not open /dev/tap{0,15}"
			sys.exit(1)
		print "[GelfInterface//Notice]: Opened", path
		return path
	
	def linux_init_interface(self):
		import fcntl
		clone_fd = os.open('/dev/net/tun', os.O_RDWR)
		for i in range(15):
			try:
				path = 'tap%d' % i
				ifr = struct.pack('16sH', path, 0x0002 | 0x1000)
				fcntl.ioctl(clone_fd, 0x400454CA, ifr)
				break
			except: #IOError as e
				path = None
				ifr = None
		if path == None:
			print "[GelfInterface//Error]: Could not open tap{0,15}"
			sys.exit(1)
		# Optionally, we want it be accessed by the normal user.
		# fcntl.ioctl(clone_fd, 0x400454CA + 2, 1000)
		self.fd = clone_fd
		return path
		pass
	
	def open_tap(self):
		import platform, subprocess
		dev = None
		if platform.system() == "Darwin":
			dev = self.darwin_init_interface()
		elif platform.system() == "Linux":
			dev = self.linux_init_interface()
		else:
			print "[GelfInterface//Error]: Unknown system", platform.system()
			sys.exit(1)
		subprocess.call(["/sbin/ifconfig", dev, "up"])
		
	def read(self):
		"""
		Read data from the configured interface.
		"""
		
		read_buffer = None
		try:
			length = struct.pack('B', len(self.hw_port)) if self.use_header else ""
			read_buffer = b"".join([length, self.hw_port, os.read(self.fd, self.mtu)])
		except OSError as e:
			print "[G_Interface//Error]:", e
			sys.exit(1)
		return read_buffer
	
	def write(self, packet):
		"""
		Write layer 3 data to interface
		"""
		write_status = -1
		if self.use_header and packet[1:packet[0]+1] == self.hw_port: 
			# If L1 headers are used, drop data originating from this virtual hw_port
			return write_status
		try:
			data = packet[packet[0]+1:] if self.use_header else packet
			write_status = os.write(self.fd, data)
		except OSError as e:
			print e
			sys.exit(1)
		return write_status

class GelfOutgoingThread(threading.Thread):
	def __init__(self, interface, ws):
		threading.Thread.__init__(self)
		self.ws = ws
		self.interface = interface
		self.kill_received = False
	
	def run(self):
		print "[T_Outgoing//Notice]: Running"
		
		while not self.kill_received:
			packet = self.interface.read()
			self.ws.broadcast(BinaryMessage(packet))


class GelfIncomingClient(WebSocketClient):
	def __init__(self, interface=None, host=None, port=None):
		self.host = host
		self.port = port
		WebSocketClient.__init__(self, 'ws://%s:%s/ws' % (host, port), protocols=['http-only', 'chat'])
		self.interface = interface
		self.kill_received = False	
		
	def opened(self):
		print "[GelfIncomingThread//Debug]: Running"
		
	def received_message(self, m):
		"""
		Read from g_int.read() and write to g_eng.outgoing
		"""
		if self.interface is not None:
			print "[GelfIncomingThread//Debug]: received packet", repr(m)
			self.interface.write(m.data)

class GelfRelayThread(threading.Thread):
	ws = None
	started = None
	def __init__(self, host, port, ws):
		threading.Thread.__init__(self)
		self.ws = ws
		self.host = host
		self.port = port
		
	def run(self):
		if ws is None:
			print "[GelfRelayThread//Error]: WS not provided"
			return
		# Cherrypy configurations
		cherrypy.config.update({
			"server.socket_host": self.host,
			"server.socket_port": self.port,
			"tools.staticdir.root": os.path.abspath(os.path.join(os.path.dirname(__file__), 'static'))
		})
		ws.subscribe()
		cherrypy.tools.websocket = WebSocketTool()
	
		# Set websocket url, and static js directory	
		cherrypy.quickstart(GelfRelay(self.host, self.port), '', config={
			"/ws": {
				'tools.websocket.on': True,
				'tools.websocket.handler_cls': GelfWebSocketHandler
			},
			"/js": {
				"tools.staticdir.on": True,
				"tools.staticdir.dir": "js"
			}
		})

def start_threads(g_int, ws):
	threads = []
	#t = T_Outgoing(g_int, ws)
	#threads.append(t)
	#threads[-1].start()
	return threads

def join_threads(threads):
	for t in threads:
		t.join()
	
def joiner(signum, frame):
	print "Caught signal:", signum
	join_threads()
	sys.exit() 

if __name__ == "__main__":
	parser = argparse.ArgumentParser(description='Gelf, the layer 1 over HTTP client/server/relay.')
	parser.add_argument('--host', default='127.0.0.1', help='Hostname used by the web server, default is 127.0.0.1')
	#parser.add_argument('interface', help='The device name (relative to /dev) that gelf will attach to an http L1 relay (a tap device).')
	parser.add_argument('port', type=int, help='TCP port used by the web server')
	parser.add_argument('--ssl', action='store_true', help='Enable SSL via web socket')
	parser.add_argument("--l1h", action='store_true', help='Add a L1 header, to prevent writing to the origin interface')
	parser.add_argument("--mtu", default=1500, type=int, help="Set the size of the read buffer for the device interface")
	parser.add_argument('--enc', help='Use the provided symmetric encryption key to encrypt data')
	args = parser.parse_args()
	
	# Start read/write interface
	hw_port = b"%s-%s" % (args.host, args.port) if args.l1h else ""
	interface = GelfInterface(hw_port=hw_port, use_header=args.l1h, mtu=args.mtu)

	# Enable websocket plugin for cherrypy
	ws = WebSocketPlugin(cherrypy.engine)
	webthread = GelfRelayThread(args.host, args.port, ws)
	webthread.start()

	# Start read/write threads
	incoming = GelfIncomingClient(interface, args.host, args.port)
	outgoing = GelfOutgoingThread(interface, ws)

	time.sleep(2)
	incoming.connect()
	outgoing.start()
	
	webthread.join()
	outgoing.join()
	
	# Debugging
	"""
	while len(threads) > 0:
		try:
			threads = [t.join(1) for t in threads if t is not None and t.isAlive()]
		except KeyboardInterrupt:
			print "[Main//Debug]: Killing I/O threads"
			for t in threads:
				t.kill_received = True
	#join_threads(threads)
	#cherrypy.quickstart(g_web)
	"""


