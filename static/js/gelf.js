var gelf = {
	relays: {},
	log: function(data) {
		$('#log').val($('#log').val() + data + "\n");
		return true;
	},
	main: function(host, port) {
		/**Onload: connect to this host's ws**/
		this.add_host(window.location.hostname, window.location.port);
		
		gelf = this;
	    $('#add').click(function() {
	    	host = $('#host').val();
	    	port = $('#port').val();
	        gelf.log('Trying to connect to: ' + host + ':' + port);
	        /**Connect to an additional ws, linking the two via received_message method**/
	        if (gelf.add_host(host, port)) {
	        	$('#host').val("");
	        	$('#port').val("");
	        } else
	        	gelf.log('Error adding: ' + host + ':' + port);
	        return false;
	     });
	},
	received_message: function (ws, evt) {
	   	var i = 0;
	   	/** Hack: detect already forwarded data **/
	   	try {/**Received from client**/
	   		JSON.parse(evt.data);
	   		//this.log("Caught already forwarded message, dropping.");
	   		return;
	   	} catch (e) {/**Received from server**/}
	   	/** Broadcast to all connected sockets **/
	   	for (w in this.relays) {
	   		if (this.relays[w] == ws)
	   			/**Do not broadcast to self**/
	   			continue
	   		this.relays[w].send('{"data":"' + evt.data + '"}');
	   	}
	},
	add_host: function (host, port) {
		/**Todo: Change this to support wss**/
	    websocket = 'ws://' + host + ':' + port + '/ws';
	    if (window.WebSocket) {
	    	this.log("Connecting to " + websocket);
	    	ws = new WebSocket(websocket);
	    }
	    else if (window.MozWebSocket) {
	    	ws = MozWebSocket(websocket);
	    }
	    else {
	    	this.log('WebSocket Not Supported');
	    	return false;
	    }
	
	    window.onbeforeunload = function(e) {
	    	this.log('disconnecting all relays');

	    	if(!e) e = window.event;
	    	e.stopPropagation();
	    	e.preventDefault();
	    };
	    ws.onmessage = function (evt) {
	    	//$('#log').val($('#log').val() + "raw: received from " + this._id + '\n');
	    	this.handler.received_message(this, evt);
	     };
	    ws.onopen = function() {
	    	this.handler.log('Connected')
	    };
	    ws.onclose = function(evt) { 
	    	this.handler.log("Server disconnected")
	    };
	    ws.handler = this;
	    this.relays[host] = ws;
	    return true;
	}
};
