#!/usr/bin/env python
# -*- coding: utf-8 -*-

import time
import logging
from scsi_access import execute_scsi_command

mode_names = ["BootMode", "Burner", "HardwareVerify", "Firmware"]
WAIT_TIME_MS = 2000

class PhisonCmd(object):
	# static commands are tuples
	# commands with variables are lists
	# format: (CMD, EXPECTED_RETURN_LENGTH)
	GET_VENDOR_INFO = (
		(0x06, 0x05, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01),
		512+16
	)
	
	GET_CHIP_ID = (
		(0x06, 0x56, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
		512
	)
	
	# not a vendor specific cmd
	GET_NUM_LBAS = (
		(0x25, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
		8
	)
	
	JUMP_TO_PRAM = (
		(0x06, 0xB3, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
		0
	)
	
	JUMP_TO_BOOTMODE = (
		(0x06, 0xBF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
		0
	)
	
	LOAD_HEADER = (
		[0x06, 0xB1, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
		0
	)
	
	# Load code body at address = page*512
	# CBWCB: 06 B1 02 page_h page_l 00 00 count_h count_l
	# DATA OUT: data[count*512]
	LOAD_BODY = (
		[0x06, 0xB1, 0x02, 0xaa, 0xaa, 0x00, 0x00, 0xcc, 0xcc, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
		0
	)
	
	# Status[0] must be 55 for header load, A5 for body load.
	GET_STATUS = (
		(0x06, 0xB0, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
		8
	)
	
	# Read 512 bytes of XDATA at given address
	# CBWCB: 06 05 'R' 'A' addr_h addr_l
	# DATA IN: xdata_at_addr[512], junk[16]
	READ_MEMORY = (
		[0x06, 0x05, 0x52, 0x41, 0xaa, 0xaa, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
		512+16
	)
	
	# Write 1 byte to a given XDATA address
	# CBWCB: 06 0C 00 'P' 'h' 'I' addr_h addr_l data
	WRITE_MEMORY = (
		[0x06, 0x0C, 0x00, 0x50, 0x68, 0x49, 0xaa, 0xaa, 0xdd, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], 
		0
	)
	
	READ_BODY = [
		[0x06, 0xB2, 0x10, 0xaa, 0xaa, 0x00, 0x00, 0xcc, 0xcc, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
		0
	]
	
	SEND_PASSWORD = (
		(0x0E, 0x00, 0x01, 0x55, 0xAA, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
		0
	)
	
	SCARY_B7 = (
		(0x06, 0xB7, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
		0
	)
	
	FIRMWARE_UPDATE = (
		(0x06, 0xEE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
		64+8
	)
	
	READ_XRAM = (
		[0x06, 0x06, 0xaa, 0xaa, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
		1
	)
	
	# 0xF000 upwards seem to be (external) function registers
	WRITE_XRAM = (
		[0x06, 0x07, 0xaa, 0xaa, 0xee, 0x00, 0x00],
		1
	)
	
	READ_IRAM = (
		[0x06, 0x08, 0xaa, 0x00, 0x00, 0x00, 0x00],
		1
	)
	
	WRITE_IRAM = (
		[0x06, 0x09, 0xaa, 0xee, 0x00, 0x00],
		1
	)
	

class PhisonDevice(object):
	
	def __init__(self, device):
		self._device = device
		self._logger = logging.getLogger("drivecom.phison_device.PhisonDevice")
	
	def get_info(self):
		ret = {"chip_type": None, "chip_id":None, "firmware_version":None, "mode":None}
		vendor_info = self.get_vendor_info()
		if((vendor_info[0x17A] == ord("V")) and (vendor_info[0x17B] == ord("R"))):
			# chip type
			ret["chip_type"] = word_from_data(vendor_info, 0x17E)
		
		# mode
		ret["mode"] = mode_from_vendor_info(vendor_info)
		
		# firmware version
		ret["firmware_version"] = "%X.%.2X.%.2X" % (vendor_info[0x94], 
			vendor_info[0x95], vendor_info[0x96])
		
		# chip id
		chip_info = self._execute_phison_command(PhisonCmd.GET_CHIP_ID)
		ret["chip_id"] = "".join(("%.2X"%i) for i in chip_info[:6])
		
		
		return ret
	
	def get_run_mode(self):
		vendor_info = self.get_vendor_info()
		return mode_from_vendor_info(vendor_info)
	
	def get_vendor_info(self):
		return self._execute_phison_command(PhisonCmd.GET_VENDOR_INFO)
	
	def _execute_phison_command(self, phison_cmd, data_out=None):
		return execute_scsi_command(self._device, phison_cmd[0], 
			data_out, phison_cmd[1])
	
	def get_num_lbas(self):
		res = self._execute_phison_command(PhisonCmd.GET_NUM_LBAS)
		ret = 0
		for i in res[:4]:
			ret = (ret << 8)|i
		
		return ret+1
	
	def jump_to_pram(self):
		self._execute_phison_command(PhisonCmd.JUMP_TO_PRAM)
	
	def jump_to_bootmode(self):
		self._execute_phison_command(PhisonCmd.JUMP_TO_BOOTMODE)
	
	def transfer_data(self, data, header=0x03, body=0x02):
		#TODO: why 1024 (=2*0x200)
		# 512 for header, but what if we have now footer, then we would skip 512 byte
		# so do we always expect a footer?
		data_size = len(data) - 1024
		
		# send header
		PhisonCmd.LOAD_HEADER[0][2] = header
		self._execute_phison_command(PhisonCmd.LOAD_HEADER, data[:0x200])
		
		# get response
		res = self._execute_phison_command(PhisonCmd.GET_STATUS)
		if(res[0] != 0x55):
			raise PhisonDeviceException("Header not accepted")
		
		# send body
		address = 0
		while(data_size > 0):
			chunk_size = data_size
			if(chunk_size > 0x8000):
				chunk_size = 0x8000
			
			# address and size in 512 blocks
			cmd_address = address >> 9
			cmd_chunk = chunk_size >> 9
			PhisonCmd.LOAD_BODY[0][2] = body
			word_to_data(PhisonCmd.LOAD_BODY[0], 3, cmd_address)
			word_to_data(PhisonCmd.LOAD_BODY[0], 7, cmd_chunk)
			self._execute_phison_command(PhisonCmd.LOAD_BODY, data[address+0x200:address+0x200+chunk_size])
			
			# get response
			res = self._execute_phison_command(PhisonCmd.GET_STATUS)
			if(res[0] != 0xA5):
				raise PhisonDeviceException("Body not accepted")
			
			address += chunk_size
			size -= chunk_size
	
	def dump_firmware(self, filename):
		address = 0
		# TODO: why only 11 sections? this is specific for the firmware version!
		# header + base + 11 sections + footer
		# 0x200 + 0x6000 + 11*0x4000 +0x200
		data = bytearray(0x32400)
		header = (0x42, 0x74, 0x50, 0x72, 0x61, 0x6D, 0x43, 0x64, 
			0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
			0x14, 0x10, 0x0B, 0x18)
		insert_data(data, 0, header)
		
		while(address*0x200 < len(data)):
			length = min(0x40*0x200, (len(data)-0x400)-(address*0x200))
			temp = length/0x200
			word_to_data(PhisonCmd.READ_BODY[0], 3, address)
			word_to_data(PhisonCmd.READ_BODY[0], 7, temp)
			PhisonCmd.READ_BODY[1] = length
			self._logger.debug("%s" % PhisonCmd.READ_BODY)
			res = self._execute_phison_command(PhisonCmd.READ_BODY)
			insert_data(data, 0x200+address*0x200, res)
			address += 0x40
		
		footer = (0x74, 0x68, 0x69, 0x73, 0x20, 0x69, 0x73, 0x20, 
			0x6D, 0x70, 0x20, 0x6D, 0x61, 0x72, 0x6B, 0x00, 
			0x03, 0x01, 0x00, 0x10, 0x01, 0x04, 0x10, 0x42)
		insert_data(data, len(data)-0x200, footer)
		
		with open(filename, "wb") as firmware_file:
			firmware_file.write(data)
	
	def execute_image(filename):
		# read image
		with open(filename, "rb") as image_file:
			data = bytearray(image_file.read())
		
		# load image
		self.transfer_data(data)
		self.jump_to_pram
		
		# wait
		time.sleep(WAIT_TIME_MS/1000.0)
	
	def send_password(self, password):
		data = bytearray(0x200)
		pw = bytearray(password)
		insert_data(data, 0x10, pw)
		self._execute_phison_command(PhisonCmd.SEND_PASSWORD, data)
	
	def send_firmware(self, firmware_filename, burner_filename=None):
		mode = self.get_run_mode()
		if(mode != 1):
			# not burner mode
			if(burner_filename is None):
				raise PhisonDeviceException("Burner image needed.")
			if(mode != 0):
				# not boot mode
				# -> switch to boot mode
				self._logger.info("Switching to boot mode...")
				self.jump_to_bootmode()
				time.sleep(WAIT_TIME_MS/1000.0)
			self.execute_image(burner_filename)
		
		self._run_firmware(firmware_filename)
	
	def _run_firmware(self, firmware_filename):
		with open(firmware_filename, "rb") as firmware_file:
			data = bytearray(firmware_file.read())
		
		#TODO: Find out what this actually does...
		#self._logger.info("Sending scary B7 command (takes several seconds)...")
		#self._execute_phison_command(PhisonCmd.SCARY_B7)
		
		self._logger.info("Rebooting...")
		self.jump_to_bootmode()
		time.sleep(WAIT_TIME_MS/1000.0)
		
		self._logger.info("Sending firmware..")
		self.transfer_data(data, 0x01, 0x00)
		PhisonCmd.FIRMWARE_UPDATE[0][2] = 0x01
		PhisonCmd.FIRMWARE_UPDATE[0][3] = 0x00
		self._execute_phison_command(PhisonCmd.FIRMWARE_UPDATE)
		time.sleep(WAIT_TIME_MS/1000.0)
		
		self.transfer_data(data, 0x03, 0x02)
		PhisonCmd.FIRMWARE_UPDATE[0][2] = 0x01
		PhisonCmd.FIRMWARE_UPDATE[0][3] = 0x01
		self._execute_phison_command(PhisonCmd.FIRMWARE_UPDATE)
		time.sleep(WAIT_TIME_MS/1000.0)
		
		PhisonCmd.FIRMWARE_UPDATE[0][2] = 0x00
		PhisonCmd.FIRMWARE_UPDATE[0][3] = 0x00
		self._execute_phison_command(PhisonCmd.FIRMWARE_UPDATE)
		time.sleep(WAIT_TIME_MS/1000.0)
		
		PhisonCmd.FIRMWARE_UPDATE[0][2] = 0x00
		PhisonCmd.FIRMWARE_UPDATE[0][3] = 0x01
		self._execute_phison_command(PhisonCmd.FIRMWARE_UPDATE)
		time.sleep(WAIT_TIME_MS/1000.0)
		
		self._logger.info("Executing...")
		self.jump_to_pram()
		time.sleep(WAIT_TIME_MS/1000.0)
		
		self._logger.info("Mode: %s" % mode_names[self.get_run_mode()])
		
	def dump_xram(self):
		data = bytearray()
		for address in xrange(0xF000):
			word_to_data(PhisonCmd.READ_XRAM[0], 2, address)
			self._logger.debug("read xram at %.4X" % address)
			res = self._execute_phison_command(PhisonCmd.READ_XRAM)
			data.append(res[0])
		
		return data
	
	# count: number of 512 byte blocks
	def read_nand(self, address, count):
		word_to_data(PhisonCmd.READ_BODY[0], 3, address)
		word_to_data(PhisonCmd.READ_BODY[0], 7, count)
		PhisonCmd.READ_BODY[1] = count*512
		self._logger.debug("%s" % PhisonCmd.READ_BODY)
		res = self._execute_phison_command(PhisonCmd.READ_BODY)
		return res
	
	def read_xram(self, address):
		word_to_data(PhisonCmd.READ_XRAM[0], 2, address)
		data = self._execute_phison_command(PhisonCmd.READ_XRAM)
		return data[0]
	
	def write_xram(self, address, value):
		word_to_data(PhisonCmd.WRITE_XRAM[0], 2, address)
		PhisonCmd.WRITE_XRAM[0][4] = value & 0xFF
		self._execute_phison_command(PhisonCmd.WRITE_XRAM)
	
	def read_iram(self, address):
		PhisonCmd.READ_IRAM[0][2] = address & 0xFF
		data = self._execute_phison_command(PhisonCmd.READ_IRAM)
		return data[0]
	
	def write_iram(self, address, value):
		PhisonCmd.WRITE_IRAM[0][2] = address & 0xFF
		PhisonCmd.WRITE_IRAM[0][3] = value & 0xFF
		self._execute_phison_command(PhisonCmd.WRITE_IRAM)
		

class PhisonDeviceException(Exception):
	pass

def mode_from_vendor_info(vendor_info):
	mode = None
	if((vendor_info[0x17A] == ord("V")) and (vendor_info[0x17B] == ord("R"))):
		#TODO: Fix this, this is a dumb way of detecting it
		mode_string = "".join(chr(i) for i in vendor_info[0xA0:0xA8])
		try:
			mode = (" PRAM   ", " FW BURN", 
				" HV TEST").index(mode_string)
		except ValueError:
			# "Firmware"
			mode = 3
	
	return mode

def word_from_data(data, offset):
	ret = data[offset] << 8
	ret += data[offset+1]
	return ret

def word_to_data(data, offset, value):
	data[offset] = (value >> 8) & 0xFF
	data[offset+1] = value & 0xFF

def insert_data(data, offset, value_list):
	for i in xrange(len(value_list)):
		data[offset+i] = value_list[i]
