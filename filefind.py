"""
	filefind.py
		A Find in Files Utility for the ROX Desktop.

	Copyright 2005 Kenneth Hayber <ken@hayber.us>
		All rights reserved.

	This program is free software; you can redistribute it and/or modify
	it under the terms of the GNU General Public License as published by
	the Free Software Foundation; either version 2 of the License.

	This program is distributed in the hope that it will be useful
	but WITHOUT ANY WARRANTY; without even the implied warranty of
	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
	GNU General Public License for more details.

	You should have received a copy of the GNU General Public License
	along with this program; if not, write to the Free Software
	Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""

from __future__ import generators

import rox, os, sys, popen2, signal
from rox import filer, Menu, tasks, basedir, mime

import gtk, os, sys, signal, re, string, socket, time, popen2, Queue, pango, gobject


APP_NAME = 'Find'
APP_SITE = 'hayber.us'
APP_PATH = rox.app_dir

MAX_HISTORY = 10

#Options.xml processing
from rox.options import Option
rox.setup_app_options(APP_NAME, site=APP_SITE)
Menu.set_save_name(APP_NAME, site=APP_SITE)

OPT_FIND_CMD = Option('find_cmd', 'find "$Path" -name "$Files" -exec grep -Hn "$Text" "{}" \;')
OPT_EDIT_CMD = Option('edit_cmd', None)

rox.app_options.notify()


use_combo_box = False #hasattr(gtk, 'ComboBox')
if use_combo_box:
	_entryClass = gtk.ComboBoxEntry
else:
	_entryClass = gtk.Entry

class EntryThing(_entryClass):
	'''this class does two things.
		1) it wraps gtk.Entry | gtk.ComboBoxEntry for backwards compatibility
		2) it adds history support
	''' 
	def __init__(self, history=None):
		self.history = history
		self.liststore = gtk.ListStore(gobject.TYPE_STRING)
		if use_combo_box:
  			_entryClass.__init__(self, self.liststore, 0)
  		else:
  			_entryClass.__init__(self)
			try: #for gtk < 2.4 compatibility and in case nothing is saved yet
				completion = gtk.EntryCompletion()
				self.set_completion(completion)
				completion.set_model(self.liststore)
				completion.set_text_column(0)
			except:
				pass
				
		self.load()
		
	def __del__(self):
		self.write()
  			
  	def get_text(self):
  		if use_combo_box:
  			return self.get_active_text()
  		else:
  			return _entryClass.get_text(self)
  	
  	def set_text(self, text):
		self.append_text(text)
  		if use_combo_box:
  			index = self.find_text(text)
  			if index != None:
  				self.set_active(index)
  		else:
  			_entryClass.set_text(self, text)
   	
   	def find_text(self, text):
		item = self.liststore.get_iter_first()
		index = 0
		while item:
			old_item = self.liststore.get_value(item, 0)
			if old_item == text:
				return index 
			item = self.liststore.iter_next(item)
			index += 1
		return None
   		
  	def append_text(self, text):
  		if self.find_text(text) == None:
			if len(self.liststore) >= MAX_HISTORY:
				self.liststore.remove(self.liststore.get_iter_first())
			self.liststore.append([text])
  					
  	def write(self):
		if not self.history:
			return

		def func(model, path, item, history_file):
			history_file.write(model.get_value(item, 0)+'\n')

		try:
			save_dir = basedir.save_config_path(APP_SITE, APP_NAME)
			history_file = file(os.path.join(save_dir, self.history), 'w')
			self.liststore.foreach(func, history_file)
		except:
			pass
  		
  	def load(self):
		if not self.history:
			return

		try:
			save_dir = basedir.save_config_path(APP_SITE, APP_NAME)
			history_file = file(os.path.join(save_dir, self.history), 'r')
			lines = history_file.readlines()
			for x in lines:
				self.liststore.append([x[:-1]])
			history_file.close()
		except:
			pass  
			


class FindWindow(rox.Window):
	def __init__(self, in_path = None):
		rox.Window.__init__(self)
		self.set_title(APP_NAME)
		self.set_default_size(550, 500)
		
		self.cancel = False
		self.running = False
		self.selected = False
		self.path = ''
		self.what = ''
		self.where = ''
		
		toolbar = gtk.Toolbar()
		toolbar.set_style(gtk.TOOLBAR_ICONS)
		toolbar.insert_stock(gtk.STOCK_CLOSE, _('Close'), None, self.close, None, -1)
		self.show_btn = toolbar.insert_stock(gtk.STOCK_GO_UP, _('Show file'), None, self.show_dir, None, -1)
		self.find_btn = toolbar.insert_stock(gtk.STOCK_EXECUTE, _('Find'), None, self.start_find, None, -1)
		self.clear_btn = toolbar.insert_stock(gtk.STOCK_CLEAR, _('Clear'), None, self.clear, None, -1)
		self.cancel_btn = toolbar.insert_stock(gtk.STOCK_STOP, _('Cancel'), None, self.cancel_find, None, -1)
		toolbar.insert_stock(gtk.STOCK_PREFERENCES, _('Settings'), None, self.edit_options, None, -1)

		self.show_btn.set_sensitive(False)
		self.find_btn.set_sensitive(False)
		self.clear_btn.set_sensitive(False)
		self.cancel_btn.set_sensitive(False)

		# Create layout, pack and show widgets
		table = gtk.Table(5, 2, False)
		x_pad = 2
		y_pad = 1

		path = EntryThing('path')
		table.attach(gtk.Label(_('Path')), 0, 1, 2, 3, 0, 0, 4, y_pad)
		table.attach(path, 1, 2, 2, 3, gtk.EXPAND|gtk.FILL, 0, x_pad, y_pad)
		if hasattr(gtk, 'FileChooserDialog'):
			self.browse = gtk.Button(label='...')
			self.browse.connect('clicked', self.browser, path)
			table.attach(self.browse, 2, 3, 2, 3, 0, 0, x_pad, y_pad)

		what = EntryThing('pattern')
		table.attach(gtk.Label(_('Pattern')),	0, 1, 3, 4, 0, 0, 4, y_pad)
		table.attach(what, 1, 2, 3, 4, gtk.EXPAND|gtk.FILL, 0, x_pad, y_pad)

		where = EntryThing('files')
		table.attach(gtk.Label(_('Files')),	0, 1, 4, 5, 0, 0, 4, y_pad)
		table.attach(where, 1, 2, 4, 5, gtk.EXPAND|gtk.FILL, 0, x_pad, y_pad)

		#######################################
		swin = gtk.ScrolledWindow()
		swin.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
		swin.set_shadow_type(gtk.SHADOW_IN)

		self.store = gtk.ListStore(str, int, str)
		view = gtk.TreeView(self.store)
		self.view = view
		swin.add(view)
		view.set_rules_hint(True)

		cell = gtk.CellRendererText()
		try: #for pre gtk 2.6.0 support
			cell.set_property('ellipsize_set', True)
			cell.set_property('ellipsize', pango.ELLIPSIZE_START)
		except: pass
		column = gtk.TreeViewColumn(_('Filename'), cell, text = 0)
		view.append_column(column)
		column.set_resizable(True)
		column.set_reorderable(True)

		cell = gtk.CellRendererText()
		column = gtk.TreeViewColumn(_('Line'), cell, text = 1)
		view.append_column(column)
		column.set_resizable(True)
		column.set_reorderable(True)

		cell = gtk.CellRendererText()
		column = gtk.TreeViewColumn(_('Text'), cell, text = 2)
		view.append_column(column)
		column.set_resizable(True)
		column.set_reorderable(True)

		view.connect('row-activated', self.activate)
		self.selection = view.get_selection()
		self.selection.connect('changed', self.set_selection)

		vbox = gtk.VBox()
		self.add(vbox)
		vbox.pack_start(toolbar, False, False)
		vbox.pack_start(table, False, False)
		vbox.pack_start(swin, True, True)
		vbox.show_all()

		what.connect('changed', self.entry_changed, what, 'what')
		where.connect('changed', self.entry_changed, where, 'where')
		path.connect('changed', self.entry_changed, path, 'path')
		
		if in_path:
			path.set_text(in_path)
			
		self.connect('delete_event', self.delete_event)
		self.path_entry = path
		self.what_entry = what
		self.where_entry = where


	def start_find(self, *args):
		self.cancel = False
		self.running = True
		self.set_sensitives()
		
		self.path_entry.append_text(self.path)
		self.what_entry.append_text(self.what)
		self.where_entry.append_text(self.where)
				
		cmd = OPT_FIND_CMD.value
		cmd = string.replace(cmd, '$Path', self.path)
		cmd = string.replace(cmd, '$Files', self.where)
		cmd = string.replace(cmd, '$Text', self.what)
		thing = popen2.Popen4(cmd)
		tasks.Task(self.get_status(thing))
		
		
	def cancel_find(self, *args):
		self.cancel = True
		self.running = False
		self.set_sensitives()
		
		
	def clear(self, *args):
		self.store.clear()
		self.selected = False
		self.set_sensitives()


	def get_status(self, thing):
		outfile = thing.fromchild
		while True:
			blocker = tasks.InputBlocker(outfile)
			yield blocker
			if self.cancel:
				os.kill(thing.pid, signal.SIGKILL)
				self.cancel = False
				return
			line = outfile.readline()
			if line:
				self.set_sensitives()
				iter = self.store.append(None)
				try:
					(filename, lineno, text) = string.split(line, ':', 2)
					self.store.set(iter, 0, filename, 1, int(lineno), 2, text[:-1])
				except:
					self.store.set(iter, 2, line[:-1])
			else:
				code = thing.wait()
				if code:
					rox.info(_('There was a problem with this search'))
				break
				
		self.running = False
		self.set_sensitives()
		if not len(self.store):
			rox.info(_('Your search returned no results'))
		

	def entry_changed(self, button, widget, item):
		self.__dict__[item] = widget.get_text()
		self.set_sensitives()
		
				
	def set_sensitives(self):
		if len(self.what) and len(self.where) and len(self.path) and not self.running:
			self.find_btn.set_sensitive(True)
		else:
			self.find_btn.set_sensitive(False)
			
		self.clear_btn.set_sensitive(bool(len(self.store)))
		self.cancel_btn.set_sensitive(self.running)
		self.show_btn.set_sensitive(self.selected)
					

	def browser(self, button, path_widget):
		browser = gtk.FileChooserDialog(title=_('Select folder'), buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_ACCEPT))
		if not len(self.path):
			self.path = os.path.expanduser('~')
		browser.set_current_folder(self.path)
		browser.set_action(gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER)
		if browser.run() != gtk.RESPONSE_CANCEL:
			try:
				self.path = browser.get_filename()
				path_widget.set_text(self.path)
			except:
				rox.report_exception()
		browser.hide()
		
		
	def set_selection(self, *args):
		self.selected = True
		self.set_sensitives()
		

	def activate(self, view, path, column):
		def get_type_handler(dir, mime_type):
			"""Lookup the ROX-defined run action for a given mime type."""
			path = basedir.load_first_config('MIME-types')
			handler = os.path.join(path, '%s_%s' % (mime_type.media, mime_type.subtype))
			if os.path.exists(handler):
				return handler
			else: #fall back to the base handler if no subtype handler exists
				handler = os.path.join(path, '%s' % (mime_type.media,), '')
				if os.path.exists(handler):
					return handler
				else:
					return None
			
		model, iter = self.view.get_selection().get_selected()
		if iter:
			filename = model.get_value(iter, 0)
			line = model.get_value(iter, 1)
			
			if len(OPT_EDIT_CMD.value):
				cmd = OPT_EDIT_CMD.value
				cmd = string.replace(cmd, '$File', filename)
				cmd = string.replace(cmd, '$Line', str(line))
				popen2.Popen4(cmd)
			else: #use the ROX defined text handler
				mime_type = rox.mime.lookup('text/plain')
				handler = get_type_handler('MIME-types', mime_type)
				handler_appdir = os.path.join(handler, 'AppRun')
				if os.path.isdir(handler) and os.path.isfile(handler_appdir):
					handler = handler_appdir
				if handler:
					popen2.Popen4('%s "%s"' % (handler, filename))
				else:
					rox.info(_('There is no run action defined for text files!'))


	def button_press(self, text, event):
		'''Popup menu handler'''
		if event.button != 3:
			return 0
		self.menu.popup(self, event)
		return 1


	def show_dir(self, *args):
		''' Pops up a filer window. '''
		model, iter = self.view.get_selection().get_selected()
		if iter:
			filename = model.get_value(iter, 0)
			filer.show_file(filename)


	def edit_options(self, *args):
		'''Show Options dialog'''
		rox.edit_options()


	def get_options(self):
		'''Get changed Options'''
		pass


	def delete_event(self, ev, e1):
		'''Bye-bye'''
		self.close()


	def close(self, *args):
		'''We're outta here!'''
		self.path_entry.write()
		self.what_entry.write()
		self.where_entry.write()
		self.destroy()
		