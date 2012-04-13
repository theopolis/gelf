import argparse
import threading
import sys
import os
import time
import struct
import base64
import select
import signal

import cherrypy

from ws4py.server.cherrypyserver import WebSocketPlugin, WebSocketTool
from ws4py.websocket import WebSocket
from ws4py.messaging import TextMessage
from ws4py.client.threadedclient import WebSocketClient

#Global resolution
DEBUG = False

class GelfRelay(object):
	def __init__(self, host, port):
		self.host = host
		self.port = port
		self.scheme = 'ws'
		pass
	
	@cherrypy.expose
	def ws(self):
		if DEBUG:
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
      	$(document).ready(function() { gelf.main();} );
      </script>
    </head>
    <body>
    <form action='#' id='relayform' method='get'>
      <textarea id='log' cols='5' rows='5' style="width:100%%"></textarea>
      <br />
      <label for='message'>new: </label><input type='text' id='host' /> <input type='text' id='port' />
      <input id='add' type='button' value='Add' />
      </form>
    </body>
    </html>
    """ % {'scheme': self.scheme}
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
		cherrypy.engine.publish('websocket-broadcast', TextMessage(reason))

class GelfInterface():
	def __init__(self, mtu=1500, enc=False, key=None):
		"""
		Open a tap interface for reading/writing, supports OS X (tuntap driver) and Linux.
		
		Keyword Arguments:
			mtu -- set the size of the read buffer
		"""
		if enc:
			if key is None:
				"""Encryption enabled, no key provided"""
				self.key = os.urandom(16) #128=16*8
				print "Encryption key:", self.key.encode("hex")
			else:
				"""Key provided as hex"""
				try:
					self.key = key.decode("hex") 
					print "Encryption enabled"
				except:
					print "[GelfInterface//Error]: Incorrect key provided"
					self.key = None
		else:
			self.key = None
		self.mtu = mtu
		self.fd = None
		
		self.open_tap()
	
	def shutdown(self):
		try:
			os.close(self.fd)
		except:
			return
	
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
		if DEBUG:
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
		print "Created interface:", dev
		subprocess.call(["/sbin/ifconfig", dev, "up"])
	
	def encrypt(self, data):
		"""
		When a symmetric key is set, use AES CFB with an IV.
		This makes the data slightly larger, 16bytes for IV, and 4 bytes for CRC
		IV    = unique per packet
		C     = AES(k, packet, iv)
		cksum = crc32 of packet"""
		iv = os.urandom(16)
		encryptor = AES.new(self.key, AES.MODE_CFB, iv)
		data += struct.pack('i', zlib.crc32(data))
		return ''.join([iv, encryptor.encrypt(data)])
		pass
	
	def decrypt(self, data):
		"""
		When a symmetric key is set, use AES CFB with an IV.
		Expect data as |-16B-IV-|---Packet---|-4B-CRC-|"""
		iv = data[:16]
		decryptor = AES.new(self.key, AES.MODE_CFB, iv)
		data = decryptor.decrypt(data[16:])
		data, crc = (data[:-4], data[-4:])
		if not crc == struct.pack('i', zlib.crc32(data)):
			if DEBUG:
				print "[GelfInterface//Notice]: Incorrect CRC"
			data = ""
		return data
		pass
		
	def read(self):
		"""
		Read data from the configured interface.
		"""
		
		read_buffer = None
		inputs = [self.fd]
		try:
			readable, _, _ = select.select(inputs, [], inputs)
			for fd in readable:
				if fd is self.fd:
					read_buffer = os.read(fd, self.mtu)
					if self.key is not None:
						"""Encryption enabled"""
						read_buffer = self.encrypt(read_buffer)
					read_buffer = base64.b64encode(read_buffer)
		except OSError as e:
			print "[GelfInterface//Error]:", e
			sys.exit(1)
		if DEBUG:
			print "[GelfInterface//Notice]: Read data: ", len(read_buffer)
		return read_buffer
	
	def write(self, packet):
		import json
		"""
		Write layer 3 data to interface
		"""
		write_status = -1
		try:
			write_buffer = json.loads(str(packet))
			write_buffer = base64.b64decode(write_buffer["data"])
		except (ValueError, TypeError):
			return write_status
		
		if self.key is not None:
			"""Encryption enabled"""
			write_buffer = self.decrypt(write_buffer)
		try:
			if DEBUG:
				print "[GelfInterface//Notice]: Write Packet: ", len(write_buffer)
			write_status = os.write(self.fd, write_buffer)
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
		if DEBUG:
			print "[GelfOutgoingThread//Notice]: Running"
		
		while not self.kill_received:
			packet = self.interface.read()
			self.ws.broadcast(TextMessage(packet))


class GelfIncomingClient(WebSocketClient):
	def __init__(self, interface=None, host=None, port=None):
		self.host = host
		self.port = port
		WebSocketClient.__init__(self, 'ws://%s:%s/ws' % (host, port), protocols=['http-only', 'chat'])
		self.interface = interface
		self.kill_received = False	
		
	def opened(self):
		if DEBUG:
			print "[GelfIncomingThread//Debug]: Running"
		
	def received_message(self, m):
		"""
		Read from g_int.read() and write to g_eng.outgoing
		"""
		if self.interface is not None:
			if DEBUG:
				print "[GelfIncomingThread//Debug]: received packet", repr(m)
			self.interface.write(m.data)

class GelfRelayThread(threading.Thread):
	"""
	Start a Cherrypy HTTP server in a thread.
	When the server starts, a WebSocket will also start, and Gelf will connect with a surrogate client.
	"""
	ws = None
	started = None
	def __init__(self, host, port, ws):
		threading.Thread.__init__(self)
		self.ws = ws
		self.host = host
		self.port = port
		
	def run(self):
		if ws is None:
			print "[GelfRelayThread//Error]: WebSocket not provided"
			return
		# Cherrypy configurations
		cherrypy.config.update({
			"server.environment": "development" if DEBUG else "production",
			"log.screen": True if DEBUG else False,
			"server.socket_host": self.host,
			"server.socket_port": self.port,
			"tools.staticdir.root": os.path.abspath(os.path.join(os.path.dirname(__file__), 'static'))
		})
		ws.subscribe()
		cherrypy.tools.websocket = WebSocketTool()
	
		print "Relay listening:", self.host, self.port
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

def handler(signal, frmae):
	"""Convert CTL+C (SIGINT) to a SIGTERM."""
	print "I'm dead"
	os.kill(os.getpid(), 15)

if __name__ == "__main__":
	parser = argparse.ArgumentParser(description='Gelf, the layer 1 over HTTP client/server/relay.')
	parser.add_argument('--host', default='127.0.0.1', help='Hostname used by the web server, default is 127.0.0.1.')
	parser.add_argument('port', type=int, help='TCP port used by the web server.')
	parser.add_argument('--ssl', action='store_true', help='[Not Implemented] Enable SSL via web socket.')
	parser.add_argument("--mtu", default=1500, type=int, help="Set the size of the read buffer for the device interface.")
	parser.add_argument('--key', help='Use the provided symmetric encryption key, in hex format.')
	parser.add_argument('--enc', action='store_true', help='Enable symmetric encryption, use without --key to generate a key.')
	parser.add_argument('-d', default=False, action='store_true', help='Turn debugging on.')
	args = parser.parse_args()
	
	DEBUG = args.d
	
	# Ultra-hack, kill everything with a CTRL+c
	signal.signal(signal.SIGINT, handler)
	
	# Encryption options
	if args.key:
		args.enc = True
	if args.enc:
		from Crypto.Cipher import AES
		import zlib
	
	# Start read/write interface
	interface = GelfInterface(mtu=args.mtu, enc=args.enc, key=args.key)

	# Enable websocket plugin for cherrypy
	ws = WebSocketPlugin(cherrypy.engine)
	webthread = GelfRelayThread(args.host, args.port, ws)
	webthread.start()

	# Start read/write threads
	incoming = GelfIncomingClient(interface, args.host, args.port)
	outgoing = GelfOutgoingThread(interface, ws)
	outgoing.daemon = True

	time.sleep(2)
	incoming.connect()
	outgoing.start()

	signal.pause()
	
	#webthread.join()
	
	#outgoing.join()
	#webthread.join()


