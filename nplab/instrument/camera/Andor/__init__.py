# -*- coding: utf-8 -*-

from nplab.utils.gui import QtWidgets, QtCore, uic, QtGui
from nplab.instrument.camera.camera_scaled_roi import CameraRoiScale, DisplayWidgetRoiScale
from nplab.instrument.camera.Andor.andor_sdk import AndorBase
from nplab.utils.notified_property import register_for_property_changes
import nplab.datafile as df

import os
import numpy as np
from nplab.ui.ui_tools import UiTools
from weakref import WeakSet


class Andor(CameraRoiScale, AndorBase):

    def __init__(self, settings_filepath=None, **kwargs):
        AndorBase.__init__(self)
        CameraRoiScale.__init__(self)

        self.CurImage = None
        self.background = None
        self.backgrounded = False

        if settings_filepath is not None:
            self.load_params_from_file(settings_filepath)
        self.isAborted = False

        self.detector_shape = self.DetectorShape  # passing the Andor parameter to the CameraRoiScale class

    def __del__(self):
        # Need to explicitly call this method so that the shutdown procedure is followed correctly
        AndorBase.__del__(self)

    '''Used functions'''

    def get_metadata(self,
                     property_names=[],
                     include_default_names=True,
                     exclude=None
                     ):
        """
        Prevents printing a load of statements everytime the metadata is called.
        TODO: rewrite the AndorProperties so that they are not unnecessarily verbose
        """
        level = self._logger.level
        self._logger.setLevel('WARN')
        diction = super(Andor, self).get_metadata(property_names, include_default_names, exclude)
        self._logger.setLevel(level)
        return diction

    metadata = property(get_metadata)

    def raw_snapshot(self):
        try:
            imageArray, num_of_images, image_shape = self.capture()

            # The image is reversed depending on whether you read in the conventional CCD register or the EM register,
            # so we reverse it back
            if self._parameters['OutAmp']:
                reshaped = np.reshape(imageArray, (num_of_images,) + image_shape)[..., ::-1]
            else:
                reshaped = np.reshape(imageArray, (num_of_images,) + image_shape)
            if num_of_images == 1:
                reshaped = reshaped[0]
            self.CurImage = self.bundle_metadata(reshaped)
            return True, self.CurImage
        except Exception as e:
            self._logger.warn("Couldn't Capture because %s" % e)

    def filter_function(self, frame):
        if self.backgrounded:
            return frame - self.background
        else:
            return frame

    def get_camera_parameter(self, parameter_name):
        return self.get_andor_parameter(parameter_name)

    def set_camera_parameter(self, parameter_name, *parameter_value):
        try:
            self.set_andor_parameter(parameter_name, *parameter_value)
        except Exception as e:
            self.log('parameter %s could not be set with the value %s due to error %s' % (parameter_name,
                                                                                          parameter_value, e))

    @property
    def roi(self):
        return tuple(map(lambda x: x - 1, self.Image[2:]))

    @roi.setter
    def roi(self, value):
        image = self.Image
        self.Image = image[:2] + tuple(map(lambda x: x + 1, value))

    @property
    def binning(self):
        return self.Image[:2]

    @binning.setter
    def binning(self, value):
        if not isinstance(value, tuple):
            value = (value, value)
        image = self.Image
        self.Image = value + image[2:]

    def get_control_widget(self):
        return AndorUI(self)

    def get_preview_widget(self):
        self._logger.debug('Getting preview widget')
        if self._preview_widgets is None:
            self._preview_widgets = WeakSet()
        new_widget = DisplayWidgetRoiScale()
        self._preview_widgets.add(new_widget)

        return new_widget

    def set_image(self, *params):
        """Set camera parameters for either the IsolatedCrop mode or Image mode

        Parameters
        ----------
        params  optional, inputs for either the IsolatedCrop mode or Image mode

        Returns
        -------

        """
        AndorBase.set_image(self, *params)


class AndorUI(QtWidgets.QWidget, UiTools):
    ImageUpdated = QtCore.Signal()

    def __init__(self, andor):
        assert isinstance(andor, Andor), "instrument must be an Andor"
        super(AndorUI, self).__init__()
        self.Andor = andor
        self.DisplayWidget = None

        uic.loadUi((os.path.dirname(__file__) + '/andor.ui'), self)

        self._setup_signals()
        self.init_gui()
        self.binning()
        self.data_file = None
        self.save_all_parameters = False

        self.gui_params = ['ReadMode', 'Exposure',
                           'AcquisitionMode', 'OutAmp', 'TriggerMode']
        self._func_dict = {}
        for param in self.gui_params:
            func = self.callback_to_update_prop(param)
            self._func_dict[param] = func
            register_for_property_changes(self.Andor, param, self._func_dict[param])

    def __del__(self):
        self._stopTemperatureThread = True
        if self.DisplayWidget is not None:
            self.DisplayWidget.hide()
            self.DisplayWidget.close()

    def _setup_signals(self):
        self.comboBoxAcqMode.activated.connect(self.acquisition_mode)
        self.comboBoxBinning.activated.connect(self.binning)
        self.comboBoxReadMode.activated.connect(self.read_mode)
        self.comboBoxTrigMode.activated.connect(self.trigger)
        self.spinBoxNumFrames.valueChanged.connect(self.number_frames)
        self.spinBoxNumFrames.setRange(1, 1000000)
        self.spinBoxNumAccum.valueChanged.connect(self.number_accumulations)
        self.spinBoxNumRows.valueChanged.connect(self.number_rows)
        self.spinBoxCenterRow.valueChanged.connect(self.number_rows)
        self.checkBoxROI.stateChanged.connect(self.ROI)
        self.checkBoxCrop.stateChanged.connect(self.isolated_crop)
        self.checkBoxCooler.stateChanged.connect(self.cooler)
        self.checkBoxEMMode.stateChanged.connect(self.output_amplifier)
        self.spinBoxEMGain.valueChanged.connect(self.em_gain)
        self.lineEditExpT.editingFinished.connect(self.exposure)
        self.lineEditExpT.setValidator(QtGui.QDoubleValidator())
        self.pushButtonDiv5.clicked.connect(lambda: self.exposure('/'))
        self.pushButtonTimes5.clicked.connect(lambda: self.exposure('x'))

        self.pushButtonCapture.clicked.connect(self.Capture)
        self.pushButtonLive.clicked.connect(self.Live)
        self.pushButtonAbort.clicked.connect(self.Abort)
        self.save_pushButton.clicked.connect(self.Save)
        self.pushButtonTakeBG.clicked.connect(self.take_background)
        self.checkBoxRemoveBG.stateChanged.connect(self.remove_background)
        self.referesh_groups_pushButton.clicked.connect(self.update_groups_box)

    def init_gui(self):
        trig_modes = {0: 0, 1: 1, 6: 2}
        self.comboBoxAcqMode.setCurrentIndex(self.Andor._parameters['AcquisitionMode'] - 1)
        self.acquisition_mode()
        self.comboBoxReadMode.setCurrentIndex(self.Andor._parameters['ReadMode'])
        self.read_mode()
        self.comboBoxTrigMode.setCurrentIndex(trig_modes[self.Andor._parameters['TriggerMode']])
        self.trigger()
        self.comboBoxBinning.setCurrentIndex(np.log2(self.Andor._parameters['Image'][0]))
        self.binning()
        self.spinBoxNumFrames.setValue(self.Andor._parameters['NKin'])

        self.Andor.get_camera_parameter('AcquisitionTimings')
        self.lineEditExpT.setText(
            str(float('%#e' % self.Andor._parameters['AcquisitionTimings'][0])).rstrip('0'))

    def cooler(self):
        self.Andor.cooler = self.checkBoxCooler.isChecked()

    def acquisition_mode(self):
        available_modes = ['Single', 'Accumulate', 'Kinetic', 'Fast Kinetic']
        currentMode = self.comboBoxAcqMode.currentText()
        self.Andor.set_camera_parameter('AcquisitionMode', available_modes.index(currentMode) + 1)

        if currentMode == 'Fast Kinetic':
            self.spinBoxNumRows.show()
            self.labelNumRows.show()
        elif self.comboBoxReadMode.currentText() != 'Single track':
            self.spinBoxNumRows.hide()
            self.labelNumRows.hide()
        if currentMode == 'Accumulate':
            self.spinBoxNumAccum.show()
            self.labelNumAccum.show()
        else:
            self.spinBoxNumAccum.hide()
            self.labelNumAccum.hide()

    def read_mode(self):
        available_modes = ['FVB', 'Multi-track', 'Random track', 'Single track', 'Image']
        currentMode = self.comboBoxReadMode.currentText()
        self.Andor.set_camera_parameter('ReadMode', available_modes.index(currentMode))
        if currentMode == 'Single track':
            self.spinBoxNumRows.show()
            self.labelNumRows.show()
            self.spinBoxCenterRow.show()
            self.labelCenterRow.show()
        elif self.comboBoxAcqMode.currentText() != 'Fast Kinetic':
            self.spinBoxNumRows.hide()
            self.labelNumRows.hide()
            self.spinBoxCenterRow.hide()
            self.labelCenterRow.hide()
        else:
            self.spinBoxCenterRow.hide()
            self.labelCenterRow.hide()

    def update_ReadMode(self, index):
        self.comboBoxReadMode.setCurrentIndex(index)

    def update_TriggerMode(self, value):
        available_modes = {0: 0, 1: 1, 6: 2}
        index = available_modes[value]
        self.comboBoxTrigMode.setCurrentIndex(index)

    def update_Exposure(self, value):
        self.lineEditExpT.setText(str(value))

    def update_OutAmp(self, value):
        self.checkBoxEMMode.setCheckState(value)

    def callback_to_update_prop(self, propname):
        """Return a callback function that refreshes the named parameter."""

        def callback(value=None):
            getattr(self, 'update_' + propname)(value)

        return callback

    def trigger(self):
        available_modes = {'Internal': 0, 'External': 1, 'ExternalStart': 6}
        currentMode = self.comboBoxTrigMode.currentText()
        self.Andor.set_camera_parameter('TriggerMode', available_modes[currentMode])

    def output_amplifier(self):
        if self.checkBoxEMMode.isChecked():
            self.Andor.set_camera_parameter('OutAmp', 0)
        else:
            self.Andor.set_camera_parameter('OutAmp', 1)
        if self.checkBoxCrop.isChecked():
            self.checkBoxCrop.setChecked(False)

    def binning(self):
        current_binning = int(self.comboBoxBinning.currentText()[0])
        if self.Andor._parameters['IsolatedCropMode'][0]:
            params = list(self.Andor._parameters['IsolatedCropMode'])
            params[3] = current_binning
            params[4] = current_binning
            self.Andor._logger.debug('binning: %s' % str(params))
            self.Andor.set_image(*params)
        else:
            self.Andor.binning = current_binning
        self.Andor.FVBHBin = current_binning

    def number_frames(self):
        num_frames = self.spinBoxNumFrames.value()
        self.Andor.set_camera_parameter('NKin', num_frames)

    def number_accumulations(self):
        num_frames = self.spinBoxNumAccum.value()
        self.Andor.set_camera_parameter('NAccum', num_frames)

    def number_rows(self):
        num_rows = self.spinBoxNumRows.value()
        if self.Andor._parameters['AcquisitionMode'] == 4:
            self.Andor.set_fast_kinetics(num_rows)
        elif self.Andor._parameters['ReadMode'] == 3:
            center_row = self.spinBoxCenterRow.value()
            if center_row - num_rows < 0:
                self.Andor._logger.info(
                    'Too many rows provided for Single Track mode. Using %g rows instead' % center_row)
                num_rows = center_row
            self.Andor.set_camera_parameter('SingleTrack', center_row, num_rows)
        else:
            self.Andor._logger.info('Changing the rows only works in Fast Kinetic or in Single Track mode')

    def exposure(self, input=None):
        if input is None:
            expT = float(self.lineEditExpT.text())
        elif input == 'x':
            expT = float(self.lineEditExpT.text()) * 5
        elif input == '/':
            expT = float(self.lineEditExpT.text()) / 5
        self.Andor.Exposure = expT

    def em_gain(self):
        gain = self.spinBoxEMGain.value()
        self.Andor.set_camera_parameter('EMGain', gain)

    def isolated_crop(self):
        current_binning = int(self.comboBoxBinning.currentText()[0])
        gui_roi = self.Andor.gui_roi
        shape = self.Andor._parameters['DetectorShape']
        if self.checkBoxEMMode.isChecked():
            maxx = gui_roi[1]
            maxy = gui_roi[3]
        else:
            maxx = shape[0] - gui_roi[1]
            maxy = gui_roi[3]
        if self.checkBoxCrop.isChecked():
            if self.checkBoxROI.isChecked():
                self.checkBoxROI.setChecked(False)
            self.Andor._parameters['IsolatedCropMode'] = (1,)
            self.Andor.set_image(1, maxy, maxx, current_binning, current_binning)
        else:
            self.Andor.set_camera_parameter('IsolatedCropMode', 0, maxy, maxx, current_binning, current_binning)
            self.Andor.set_image()

    def take_background(self):
        self.Andor.background = self.Andor.raw_snapshot()[1]
        self.Andor.backgrounded = True
        self.checkBoxRemoveBG.setChecked(True)

    def remove_background(self):
        if self.checkBoxRemoveBG.isChecked():
            self.Andor.backgrounded = True
        else:
            self.Andor.backgrounded = False

    def Save(self):
        if self.data_file is None:
            self.data_file = df.current()
        data = self.Andor.CurImage
        if self.filename_lineEdit.text() != 'Filename....':
            filename = self.filename_lineEdit.text()
        else:
            filename = 'Andor_data'
        if self.group_comboBox.currentText() == 'AndorData':
            if df._use_current_group == True and df._current_group is not None:
                group = df._current_group
            elif 'AndorData' in self.data_file.keys():
                group = self.data_file['AndorData']
            else:
                group = self.data_file.create_group('AndorData')
        else:
            group = self.data_file[self.group_comboBox.currentText()]
        if np.shape(data)[0] == 1:
            data = data[0]
        if self.save_all_parameters:
            attrs = self.Andor.get_andor_parameters()
        else:
            attrs = dict()
        attrs['Description'] = self.description_plainTextEdit.toPlainText()
        if hasattr(self.Andor, 'x_axis'):
            attrs['wavelengths'] = self.Andor.x_axis
        try:
            data_set = group.create_dataset(name=filename, data=data)
        except Exception as e:
            self.Andor._logger.info(e)
        df.attributes_from_dict(data_set, attrs)
        if self.Andor.backgrounded == False and 'background' in data_set.attrs.keys():
            del data_set.attrs['background']

    def update_groups_box(self):
        if self.data_file is None:
            self.data_file = df.current()
        self.group_comboBox.clear()
        if 'AndorData' not in self.data_file.values():
            self.group_comboBox.addItem('AndorData')
        for group in self.data_file.values():
            if type(group) == df.Group:
                self.group_comboBox.addItem(group.name[1:], group)

    def ROI(self):
        if self.checkBoxROI.isChecked():
            self.Andor.roi = self.Andor.gui_roi  # binning + params
        else:
            self.Andor.roi = (0, self.Andor._parameters['DetectorShape'][0]-1,
                              0, self.Andor._parameters['DetectorShape'][1]-1)

    def Capture(self):
        self.Andor.raw_image(update_latest_frame=True)

    def Live(self):
        self.Andor.live_view = True

    def Abort(self):
        self.Andor.live_view = False


if __name__ == '__main__':
    andor = Andor()
    andor.show_gui()
