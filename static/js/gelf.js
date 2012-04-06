var gelf = {
		relays: {},
		log: function(data) {
			$('#log').val($('#log').val() + data + "\n");
			return true;
		},
		main: function(host, port) {
			this.add_host(host, port);
			
			gelf = this;
            $('#add').click(function() {
            	host = $('#host').val();
            	port = $('#port').val();
                gelf.log('Trying to connect to: ' + host + ':' + port);
                //ws.send('%(username)s: ' + $('#message').val());
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
           	try {
           		JSON.parse(evt.data);
           		this.log("Caught already forwarded message, dropping.");
           		return;
           	} catch (e) {
           		this.log(evt.data)
           	}
           	/** Broadcast to all connected sockets **/
           	for (w in this.relays) {
           		i++;
           		if (this.relays[w] == ws) {
           			/*out = '';
           			for (var i in evt) {
           				out += i + ':' + evt[i] + "\n";
           			}
           			//this.log(out);*/
           			this.log("received data from " + this.relays[w]._id);
           		} else {
           			/*temp = this.relays[w].onmessage;
           			this.relays[w].onmessage = function(evt) {
           				this.handler.log(this._id + " received delay message"); 
           				this.onmessage = temp;
           			};*/
           			this.relays[w].send('{"data":"' + evt.data + '"}');
           		}
           	}
		},
		add_host: function (host, port) {
			/** Change this to support wss **/
            websocket = 'ws://' + host + ':' + port + '/ws';
            if (window.WebSocket) {
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
              //ws.close(1000, '%(username)s left the room');
                   
              if(!e) e = window.event;
              e.stopPropagation();
              e.preventDefault();
            };
            ws.onmessage = function (evt) {
               $('#log').val($('#log').val() + "raw: received from " + this._id + '\n');
            	this.handler.received_message(this, evt);
             };
            /** hack: to stop message propagation **/
            //ws.onmessage = ws._onmessage;
            ws.onopen = function() {
               //ws.send(host + " connected");
            	//.log('connected to: ' + ws)
            	this.handler.log('Connected')
            };
            ws.onclose = function(evt) {
               //this.log('Connection closed by server: ' + evt.code + ' \"' + evt.reason + '\"');  
            	this.handler.log("Server disconnected")
            };
            ws.handler = this;
            this.relays[host] = ws;
            /** testing **/
            ws._id = host + '-' + port;
            return true;
		}
};
