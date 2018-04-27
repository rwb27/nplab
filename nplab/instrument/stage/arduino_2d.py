# -*- coding: utf-8 -*-
"""
Created on Wed Mar 28 11:17:17 2018

@author: cc831
"""

from nplab.instrument.serial_instrument import SerialInstrument 
from nplab.instrument.stage import Stage
import re
import numpy as np
import time


class arduino_2d(SerialInstrument, Stage):
    """
    This class handles the Prior stage.
    """
    port_settings = dict(baudrate=9600)
 #   termination_character = "\n" #: All messages to or from the instrument end with this character.
    termination_character = ""
    termination_line = "END" #: If multi-line responses are recieved, they must end with this string
    axis_names = ('x','y')
    def __init__(self, port=None, use_si_units = False):
        super(arduino_2d, self).__init__(port=port)
        self.calibration = 4 #change this
        self.axis_dict = {'x':'2','y':'4'}
        self.unit = 'u'
    def move_rel(self, dxy, block=True):
        """Make a relative move by dx microns/metres (see move)"""
        x_command = 'o,'+self.axis_dict['x']+','+str(dxy[0])
        y_command = 'o,'+self.axis_dict['y']+','+str(dxy[1])
        self.write(x_command)
        time.sleep(0.5)
        self.write(y_command)        
        
        