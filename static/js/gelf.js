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
           	/** Broadcast to all connected sockets **/
           	for (w in this.relays) {
           		i++;
           		if (this.relays[w] == ws) {
           			this.log("received data from " + i);
           		} else {
           			this.relays[w].send(evt.data);
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
               //$('#log').val($('#log').val() + evt.data + '\\n');
            	this.handler.received_message(this, evt);
             };
            ws.onopen = function() {
               //ws.send(host + " connected");
            	//.log('connected to: ' + ws)
            	this.handler.log('Connected')
            };
            ws.onclose = function(evt) {
               //this.log('Connection closed by server: ' + evt.code + ' \"' + evt.reason + '\"');  
            	this.handler.received_message(this, evt);
            };
            ws.handler = this;
            this.relays[host] = ws;
            return true;
		}
};
