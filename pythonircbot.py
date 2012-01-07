#    pythonircbot, module used to easily create IRC bots in Python
#    Copyright (C) 2012  Milan Boers
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Easily create IRC bots in Python

Module providing an easy interface to create IRC bots.
Uses regexes in combination with an event-like system
to handle messages, and abstracts many IRC commands.
"""

__author__ = 'Milan Boers'
__version__ = '1.0'

import socket
import threading
import thread
import re
import copy
import time
import Queue

class _SuperSocket(object):
	"""Socket with flooding control"""
	def __init__(self, sleepTime, maxItems, verbose=True, *args, **kwargs):
		super(_SuperSocket, self).__init__(*args, **kwargs)
		
		self._sleepTime = sleepTime
		self._maxItems = maxItems
		self._verbose = verbose
		self._messageQueue = Queue.Queue(self._maxItems)
		
		self._s = socket.socket()
		
		# Start the sender thread
		thread.start_new_thread(self._senderThread, ())
	
	def _senderThread(self):
		while True:
			try:
				# Block until item is available
				data = self._messageQueue.get(True)
				self._s.send(data + "\r\n")
				if self._verbose:
					print "SENT: ", data
				time.sleep(self._sleepTime)
			except:
				# Socket not alive anymore
				break
	
	def _connect(self, host, port):
		self._s.connect((host, port))
	
	def _send(self, data):
		if self._messageQueue.qsize() >= self._maxItems:
			self._messageQueue = Queue.Queue(self._maxItems)
			if self._verbose:
				print "OVERFLOWN. EMPTYING MESSAGE QUEUE."
		else:
			# Put item onto the queue
			self._messageQueue.put(data)
	
	def _recv(self):
		return self._s.recv(1024).rstrip('\r\n')
	
	def _close(self):
		self._s.close()

class _BotReceiveThread(threading.Thread):
	"""Thread in which the bot handles received messages"""
	def __init__(self, bot, verbose=True, *args, **kwargs):
		super(_BotReceiveThread, self).__init__(*args, **kwargs)
		
		self._bot = bot
		self._verbose = verbose
		self._connected = True
		
		# Event to fire when the thread is about to shut down
		self._shutdownEvent = threading.Event()
		
		self._namesList = []
		self._namesHandled = threading.Event()
	
	def run(self):
		while self._connected:
			line = self._bot._s._recv()
			
			if self._verbose:
				print "RECV: ", line
			
			if self._privMsg(line):
				continue
			if self._pong(line):
				continue
			if self._quit(line):
				continue
			if self._modeset(line):
				continue
			if self._modeunset(line):
				continue
			if self._names(line):
				continue
	
	def _quit(self, line):
		matchQuit = re.compile('^:%s!.* QUIT :' % self._bot._nick).search(line)
		if matchQuit:
			self._connected = False
			self._shutdownEvent.set()
	
	def _names(self, line):
		matchNames = re.compile('^:.* 353 %s = (.*) :(.*)' % self._bot._nick).search(line)
		if matchNames:
			# Names list
			channel = matchNames.group(1)
			names = matchNames.group(2)
			
			namesList = re.sub('\@|\+', '', names)
			namesList = namesList.split(' ')
			self._namesList = namesList
			
			self._namesHandled.set()
	
	def _privMsg(self, line):
		matchPrivmsg = re.compile('^:(.*)!~(.*) PRIVMSG (.*) :(.*)').search(line)
		if matchPrivmsg:
			# Privmsg
			nick = matchPrivmsg.group(1)
			client = matchPrivmsg.group(2)
			channel = matchPrivmsg.group(3)
			rmsg = matchPrivmsg.group(4)
			
			with self._bot._responseFunctionsLock:
				_responseFunctions = copy.copy(self._bot._responseFunctions)
			
			for func in _responseFunctions:
				thread.start_new_thread(func, (rmsg, nick, client, channel))
			
			# Return a string, just to make sure it doesn't return None
			return "continue"
	
	def _pong(self, line):
		matchPing = re.compile('^PING :(.*)').search(line)
		if matchPing:
			# Ping
			self._bot._s._send("PONG %s" % matchPing.group(1))
			return "continue"
	
	def _modeset(self, line):
		matchModeset = re.compile('^:.* MODE (.*) \+([A-Za-z]) %s$' % self._bot._nick).search(line)
		if matchModeset:
			channel = matchModeset.group(1).upper()
			mode = matchModeset.group(2)
			# Mode set
			if channel not in self._bot._modes:
				self._bot._modes[channel] = []
			self._bot._modes[channel].append(mode)
			return "continue"
	
	def _modeunset(self, line):
		matchModeunset = re.compile('^:.* MODE (.*) -([A-Za-z]) %s$' % self._bot._nick).search(line)
		if matchModeunset:
			channel = matchModeunset.group(1).upper()
			mode = matchModeunset.group(2)
			# Mode unset
			self._bot._modes[channel].remove(mode)
			return "continue"

class Bot(object):
	def __init__(self, nickname):
		"""
		Creates bot with nick as nickname
		
		Arguments:
		- nickname: Nickname of the bot
		"""
		self._nick = nickname
		
		self._connected = False
		
		self._responseFunctions = []
		self._responseFunctionsLock = threading.Lock()
		
		self._modes = dict()
	
	def connect(self, host, port=6667, verbose=False, sleepTime=1, maxItems=4):
		"""
		Connects the bot to a server. Every bot can connect to only one server.
		If you want your bot to be on multiple servers, create multiple Bot objects.
		
		Arguments:
		- host: Hostname of the server
		- port: Port the server listens to
		- verbose: If True, prints all the received and sent data
		- sleepTime: Minimum time in seconds between two sent messages (used for flood control)
		- maxItems: Maximum items in the queue. Queue is emptied after this amount is reached. 0 means unlimited. (used for flood control)
		"""
		if self._connected:
			raise Exception("Already connected. Can't connect twice.")
		
		self._verbose = verbose
		self._host = host
		self._port = port
		self._sleepTime = sleepTime
		self._maxItems = maxItems
		
		self._disconnectEvent = threading.Event()
		
		self._s = _SuperSocket(self._sleepTime, self._maxItems, self._verbose)
		self._s._connect(self._host, self._port)
		self._connected = True
		
		self.rename(self._nick)
		self._s._send("USER %s %s %s :%s" % (self._nick, self._nick, self._nick, self._nick))
		
		# Run the main loop in another thread
		self._receiveThread = _BotReceiveThread(self, self._verbose)
		self._receiveThread.start()
	
	def disconnect(self, message=''):
		"""
		Disconnects the bot from the server.
		
		Arguments:
		- message: Message to show when quitting.
		"""
		self._s._send("QUIT :%s" % message)
		# Wait for the thread to be finished
		self._receiveThread._shutdownEvent.wait()
		# Fire disconnected event
		self._disconnectEvent.set()
		self._connected = False
	
	def reconnect(self, message=''):
		"""
		Reconnects the bot to the server. Note that this does not reconnect to channels.
		
		Arguments:
		- message: Message to show when quitting.
		"""
		self._s._send("QUIT :%s" % message)
		# Wait for the thread to be finished
		self._receiveThread._shutdownEvent.wait()
		self._connected = False
		# Connect again
		self.connect(self._host, self._port, self._verbose, self._sleepTime, self._maxItems)
	
	def getModes(self, channel):
		"""
		Returns the current modes of the bot in the channel.
		
		Arguments:
		- channel: channel you want the modes of
		"""
		if channel.upper() in self._modes:
			return self._modes[channel.upper()]
		else:
			return []
	
	"""
	IRC commands
	"""
	def rename(self, nickname):
		"""
		Renames the bot.
		
		Arguments:
		- nickname: New nickname of the bot
		"""
		self._s._send("NICK %s" % nickname)
		self._nick = nickname
	
	def joinChannel(self, channel):
		"""
		Joins a channel.
		
		Arguments:
		- channel: Channel name
		"""
		self._s._send("JOIN %s" % channel)
	
	def partChannel(self, channel):
		"""
		Parts a channel.
		
		Arguments:
		- channel: Channel name
		"""
		self._s._send("PART %s" % channel)
	
	def setAway(self, message=''):
		"""
		Sets the bot to away.
		
		Arguments:
		- message: Away message
		"""
		self._s._send("AWAY :%s" % message)
	
	def setBack(self):
		"""
		Sets the bot to back (after previously having been set to away).
		"""
		self._s._send("AWAY ")
	
	def kickUser(self, channel, client, message=''):
		"""
		Kick a client from the channel.
		
		Arguments:
		- channel: Channel the client should be kicked from.
		- client: Client to be kicked.
		- message: Message to kick user with.
		"""
		self._s._send("KICK %s %s :%s" % (channel, client, message))
	
	def setMode(self, target, flag):
		"""
		Sets a user/channel flag.
		
		Arguments:
		- target: Channel or nickname of user to set the flag of
		- flag: Flag (and optional arguments) to set
		"""
		self._s._send("MODE %s +%s" % (target, flag))
	
	def unsetMode(self, target, flag):
		"""
		Unsets a user/channel flag.
		
		Arguments:
		- target: Channel or nickname of user to set the flag of
		- flag: Flag (and optional arguments) to set
		"""
		self._s._send("MODE %s -%s" % (target, flag))
	
	def inviteUser(self, nickname, channel):
		"""
		Invite user to a channel.
		
		Arguments:
		- nickname: Nickname of user to invite.
		- channel: Channel to invite user to.
		"""
		self._s._send("INVITE %s %s" % (nickname, channel))
	
	def sendMsg(self, target, message):
		"""
		Send a message to a channel or user.
		
		Arguments:
		- target: Nickname or channel name to send message to.
		- message: Message to send.
		"""
		self._s._send("PRIVMSG %s :%s" % (target, message))
	
	def sendNotice(self, target, message):
		"""
		Send a notice to a channel or user.
		
		Arguments:
		- target: Nickname or channel name to send notice to.
		- message: Message to send.
		"""
		self._s._send("NOTICE %s :%s" % (target, message))
	
	def setChannelTopic(self, channel, topic):
		"""
		Sets the topic of the channel.
		
		Arguments:
		- channel: Channel name.
		- topic: Message to change the topic to.
		"""
		self._s._send("TOPIC %s :%s" % (channel, topic))
	
	def getNames(self, channel):
		"""
		Gets the nicknames of all users in a channel.
		
		Arguments:
		- channel: Channel name.
		"""
		self._receiveThread._namesHandled.clear()
		self._s._send("NAMES %s" % channel)
		self._receiveThread._namesHandled.wait(5)
		names = copy.copy(self._receiveThread._namesList)
		self._receiveThread._namesList = []
		return names
	
	def addMsgHandler(self, function, message=".*", channel='.*', nickname='.*', client='.*', messageFlags=0, channelFlags=0, nicknameFlags=0, clientFlags=0):
		"""
		Adds a function to the list of functions that should be executed on every received message.
		Please keep in mind that the functions are all executed concurrently.
		Returns a function that can be used to remove the handler again with removeMsgHandler().
		
		Arguments:
		- function: The function that should be called
		- message: Regex that should match the message. If it does not, the function will not be called.
		- channel: Regex that should match the channel. If it does not, the function will not be called.
		- nickname: Regex that should match the nickname. If it does not, the function will not be called.
		- client: Regex that should match the client. If it does not, the function will not be called.
		- messageFlags: Flags for the message regex, as documented here: http://docs.python.org/library/re.html#re.compile
		- channelFlags: Flags for the channel regex, as documented here: http://docs.python.org/library/re.html#re.compile
		- nicknameFlags: Flags for the nickname regex, as documented here: http://docs.python.org/library/re.html#re.compile
		- clientFlags: Flags for the client regex, as documented here: http://docs.python.org/library/re.html#re.compile
		
		The function should have 5 arguments:
		- message: The first argument will be the message that was received.
		- channel: The second argument will be the channel the message was sent to. This will be the same as nickname when this was a private message.
		- nickname: The third argument will be the nickname of the user who sent the message.
		- client: The fourth argument will be the client of the user who sent this message.
		- message match: Match object (http://docs.python.org/library/re.html#match-objects) of the regex applied to the message.
		"""
		with self._responseFunctionsLock:
			responseFunction = lambda rmsg, rnick, rclient, rchannel: self._responseFunction(function, rmsg, rnick, rclient, rchannel, message, channel, nickname, client, messageFlags, channelFlags, nicknameFlags, clientFlags)
			self._responseFunctions.append(responseFunction)
			return responseFunction
	
	def removeMsgHandler(self, responseFunction):
		"""
		Remove a function from the list of functions that should be executed on every received message.
		
		Arguments:
		responseFunction: Function that is returned by addMsgHandler()
		"""
		with self._responseFunctionsLock:
			self._responseFunctions.remove(responseFunction)
	
	def waitForDisconnect(self):
		"""
		Blocks until the bot has disconnected.
		"""
		self._disconnectEvent.wait()
	
	"""
	Internal functions
	"""
	
	def _responseFunction(self, function, msg, nick, client, channel, msgConstraint, channelsConstraint, nicksConstraint, clientsConstraint, msgFlags, channelFlags, nickFlags, clientFlags):
		channelsMatch = re.compile(channelsConstraint, channelFlags).search(channel)
		if not channelsMatch:
			return
		nicksMatch = re.compile(nicksConstraint, nickFlags).search(nick)
		if not nicksMatch:
			return
		clientsMatch = re.compile(clientsConstraint, clientFlags).search(client)
		if not clientsMatch:
			return
		msgMatch = re.compile(msgConstraint, msgFlags).search(msg)
		if not msgMatch:
			return
		
		# If this was a private message, the channel is my own nick
		if channel == self._nick:
			# Set the channel to the other's nick
			channel = nick
		
		function(msg, channel, nick, client, msgMatch)