#!/usr/bin/env python
from time import time
import sys
import numpy as np
import math
import os

sys.path.append('/opt/ros/hydro/lib/python2.7/dist-packages')
import cv


'''
2012-10-10
Script developed by Henrik Skov Midtiby (henrikmidtiby@gmail.com).
Provided for free but use at your own risk.

2013-02-13 
Structural changes allows simultaneous tracking of several markers.
Frederik Hagelskjaer added code to publish marker locations to ROS.
'''

PublishToROS = False

if PublishToROS:
    import roslib; roslib.load_manifest('frobitLocator')
    import rospy
    from geometry_msgs.msg import Point
    

class MarkerTracker:
    '''
    Purpose: Locate a certain marker in an image.
    '''
    def __init__(self, order, kernelSize, scaleFactor):
        (kernelReal, kernelImag) = self.generateSymmetryDetectorKernel(order, kernelSize)
        self.order = order
        self.matReal = cv.CreateMat(kernelSize, kernelSize, cv.CV_32FC1)
        self.matImag = cv.CreateMat(kernelSize, kernelSize, cv.CV_32FC1)
        for i in range(kernelSize):
            for j in range(kernelSize):
                self.matReal[i, j] = kernelReal[i][j] / scaleFactor
                self.matImag[i, j] = kernelImag[i][j] / scaleFactor
        self.lastMarkerLocation = (None, None)
        self.orientation = None

        (kernelRealThirdHarmonics, kernelImagThirdHarmonics) = self.generateSymmetryDetectorKernel(3*order, kernelSize)
        self.matRealThirdHarmonics = cv.CreateMat(kernelSize, kernelSize, cv.CV_32FC1)
        self.matImagThirdHarmonics = cv.CreateMat(kernelSize, kernelSize, cv.CV_32FC1)
        for i in range(kernelSize):
            for j in range(kernelSize):
                self.matRealThirdHarmonics[i, j] = kernelRealThirdHarmonics[i][j] / scaleFactor
                self.matImagThirdHarmonics[i, j] = kernelImagThirdHarmonics[i][j] / scaleFactor

                  
    def generateSymmetryDetectorKernel(self, order, kernelsize):
        valueRange = np.linspace(-1, 1, kernelsize);
        temp1 = np.meshgrid(valueRange, valueRange)
        kernel = temp1[0] + 1j*temp1[1];
            
        magni = abs(kernel);
        kernel = kernel**order;
        kernel = kernel*np.exp(-8*magni**2);
         
        return (np.real(kernel), np.imag(kernel))

    def allocateSpaceGivenFirstFrame(self, frame):
        self.newFrameImage32F = cv.CreateImage((frame.width, frame.height), cv.IPL_DEPTH_32F, 3)
        self.frameReal = cv.CreateImage ((frame.width, frame.height), cv.IPL_DEPTH_32F, 1)
        self.frameImag = cv.CreateImage ((frame.width, frame.height), cv.IPL_DEPTH_32F, 1)
        self.frameRealThirdHarmonics = cv.CreateImage ((frame.width, frame.height), cv.IPL_DEPTH_32F, 1)
        self.frameImagThirdHarmonics = cv.CreateImage ((frame.width, frame.height), cv.IPL_DEPTH_32F, 1)
        self.frameRealSq = cv.CreateImage ((frame.width, frame.height), cv.IPL_DEPTH_32F, 1)
        self.frameImagSq = cv.CreateImage ((frame.width, frame.height), cv.IPL_DEPTH_32F, 1)
        self.frameSumSq = cv.CreateImage ((frame.width, frame.height), cv.IPL_DEPTH_32F, 1)

    
    def locateMarker(self, frame):
        self.frameReal = cv.CloneImage(frame)
        self.frameImag = cv.CloneImage(frame)
        self.frameRealThirdHarmonics = cv.CloneImage(frame)
        self.frameImagThirdHarmonics = cv.CloneImage(frame)

        # Calculate convolution and determine response strength.
        cv.Filter2D(self.frameReal, self.frameReal, self.matReal)
        cv.Filter2D(self.frameImag, self.frameImag, self.matImag)
        cv.Mul(self.frameReal, self.frameReal, self.frameRealSq)
        cv.Mul(self.frameImag, self.frameImag, self.frameImagSq)
        cv.Add(self.frameRealSq, self.frameImagSq, self.frameSumSq)

        # Calculate convolution of third harmonics for quality estimation.
        cv.Filter2D(self.frameRealThirdHarmonics, self.frameRealThirdHarmonics, self.matRealThirdHarmonics)
        cv.Filter2D(self.frameImagThirdHarmonics, self.frameImagThirdHarmonics, self.matImagThirdHarmonics)
        
        min_val, max_val, min_loc, max_loc = cv.MinMaxLoc(self.frameSumSq)
        self.lastMarkerLocation = max_loc
        (xm, ym) = max_loc
        self.determineMarkerOrientation(frame)
        self.determineMarkerQuality()
        return max_loc

    def determineMarkerOrientation(self, frame):    
        (xm, ym) = self.lastMarkerLocation
        realval = cv.Get2D(self.frameReal, ym, xm)[0]
        imagval = cv.Get2D(self.frameImag, ym, xm)[0]
        self.orientation = (math.atan2(-realval, imagval) - math.pi / 2) / self.order

        maxValue = 0
        maxOrient = 0
        searchDist = 10
        for k in range(self.order):
            orient = self.orientation + 2 * k * math.pi / self.order
            xm2 = int(xm + searchDist*math.cos(orient))
            ym2 = int(ym + searchDist*math.sin(orient))
            if(xm2 > 0 and ym2 > 0 and xm2 < frame.width and ym2 < frame.height):
                try:
                    intensity = cv.Get2D(frame, ym2, xm2)
                    if(intensity[0] > maxValue):
                        maxValue = intensity[0]
                        maxOrient = orient
                except:
                    print("determineMarkerOrientation: error: %d %d %d %d" % (ym2, xm2, frame.width, frame.height))
                    pass

        self.orientation = self.limitAngleToRange(maxOrient)

    def determineMarkerQuality(self):
        (xm, ym) = self.lastMarkerLocation
        realval = cv.Get2D(self.frameReal, ym, xm)[0]
        imagval = cv.Get2D(self.frameImag, ym, xm)[0]
        realvalThirdHarmonics = cv.Get2D(self.frameRealThirdHarmonics, ym, xm)[0]
        imagvalThirdHarmonics = cv.Get2D(self.frameImagThirdHarmonics, ym, xm)[0]
        argumentPredicted = 3*math.atan2(-realval, imagval)
        argumentThirdHarmonics = math.atan2(-realvalThirdHarmonics, imagvalThirdHarmonics)
        argumentPredicted = self.limitAngleToRange(argumentPredicted)
        argumentThirdHarmonics = self.limitAngleToRange(argumentThirdHarmonics)
        difference = self.limitAngleToRange(argumentPredicted - argumentThirdHarmonics)
        strength = math.sqrt(realval*realval + imagval*imagval)
        strengthThirdHarmonics = math.sqrt(realvalThirdHarmonics*realvalThirdHarmonics + imagvalThirdHarmonics*imagvalThirdHarmonics)
        #print("Arg predicted: %5.2f  Arg found: %5.2f  Difference: %5.2f" % (argumentPredicted, argumentThirdHarmonics, difference))        
        #print("angdifferenge: %5.2f  strengthRatio: %8.5f" % (difference, strengthThirdHarmonics / strength))
        # angdifference \in [-0.2; 0.2]
        # strengthRatio \in [0.03; 0.055]
        quality = math.exp(-math.pow(difference/0.3, 2))
        print("quality: %5.2f" % quality)
        
    def limitAngleToRange(self, angle):
        while(angle < math.pi):
            angle += 2*math.pi
        while(angle > math.pi):
            angle -= 2*math.pi
        return angle
            

class ImageAnalyzer:
    '''
    Purpose: Locate markers in the presented images.
    '''
    def __init__(self, downscaleFactor = 2):
        self.downscaleFactor = downscaleFactor
        self.markerTrackers = []
        self.tempImage = None
        self.greyScaleImage = None
        self.subClassesInitialized = False
        self.markerLocationsX = []
        self.markerLocationsY = []
        pass

    def addMarkerToTrack(self, order, kernelSize, scaleFactor):
        self.markerTrackers.append(MarkerTracker(order, kernelSize, scaleFactor))
        self.markerLocationsX.append(0)
        self.markerLocationsY.append(0)
        self.subClassesInitialized = False 
    
    # Is called with a colour image.
    def initializeSubClasses(self, frame):
        self.subClassesInitialized = True
        reducedWidth = frame.width / self.downscaleFactor
        reducedHeight = frame.height / self.downscaleFactor
        reducedDimensions = (reducedWidth, reducedHeight)
        self.frameGray = cv.CreateImage (reducedDimensions, cv.IPL_DEPTH_32F, 1)
        self.originalImage = cv.CreateImage(reducedDimensions, cv.IPL_DEPTH_32F, 3)
        self.reducedImage = cv.CreateImage(reducedDimensions, frame.depth, frame.nChannels)
        for k in range(len(self.markerTrackers)):
            self.markerTrackers[k].allocateSpaceGivenFirstFrame(self.reducedImage)
    
    # Is called with a colour image.
    def analyzeImage(self, frame):
        assert(frame.nChannels == 3)
        if(self.subClassesInitialized is False):
            self.initializeSubClasses(frame)

        cv.Resize(frame, self.reducedImage)

        cv.ConvertScale(self.reducedImage, self.originalImage)
        cv.CvtColor(self.originalImage, self.frameGray, cv.CV_RGB2GRAY)

        for k in range(len(self.markerTrackers)):
            markerLocation = self.markerTrackers[k].locateMarker(self.frameGray)
            (xm, ym) = markerLocation
            (xm, ym) = (self.downscaleFactor * xm, self.downscaleFactor * ym)
            self.markerLocationsX[k] = xm
            self.markerLocationsY[k] = ym
            #cv.Line(frame, (0, ym), (frame.width, ym), (0, 0, 255)) # B, G, R
            #cv.Line(frame, (xm, 0), (xm, frame.height), (0, 0, 255))

        return frame

class TrackerInWindowMode:
    def __init__(self, order = 7):
        #cv.NamedWindow('reducedWindow', cv.CV_WINDOW_AUTOSIZE)
        self.windowWidth = 100
        self.windowHeight = 100
        self.frameGray = cv.CreateImage ((self.windowWidth, self.windowHeight), cv.IPL_DEPTH_32F, 1)
        self.originalImage = cv.CreateImage((self.windowWidth, self.windowHeight), cv.IPL_DEPTH_32F, 3)
        self.markerTracker = MarkerTracker(order, 21, 2500)
        self.trackerIsInitialized = False
        self.subImagePosition = None
        pass
    
    def cropFrame(self, frame, lastMarkerLocationX, lastMarkerLocationY):
        if(not self.trackerIsInitialized):
            self.markerTracker.allocateSpaceGivenFirstFrame(self.originalImage)
            self.reducedImage = cv.CreateImage((self.windowWidth, self.windowHeight), frame.depth, 3)
        xCornerPos = lastMarkerLocationX - self.windowWidth / 2
        yCornerPos = lastMarkerLocationY - self.windowHeight / 2
        # Ensure that extracted window is inside the original image.
        if(xCornerPos < 1):
            xCornerPos = 1
        if(yCornerPos < 1):
            yCornerPos = 1
        if(xCornerPos > frame.width - self.windowWidth):
            xCornerPos = frame.width - self.windowWidth
        if(yCornerPos > frame.height - self.windowHeight):
            yCornerPos = frame.height - self.windowHeight
        try:
            self.subImagePosition = (xCornerPos, yCornerPos, self.windowWidth, self.windowHeight)
            self.reducedImage = cv.GetSubRect(frame, self.subImagePosition)
            cv.ConvertScale(self.reducedImage, self.originalImage)
            cv.CvtColor(self.originalImage, self.frameGray, cv.CV_RGB2GRAY)
        except:
            print("frame: ", frame.depth)
            print("originalImage: ", self.originalImage.height, self.originalImage.width, self.originalImage)
            print("frameGray: ", self.frameGray.height, self.frameGray.width, self.frameGray.depth)
            print "Unexpected error:", sys.exc_info()[0]
            #quit(0)
            pass
        
    def locateMarker(self):
        (xm, ym) = self.markerTracker.locateMarker(self.frameGray)
        #xm = 50
        #ym = 50
        #cv.Line(self.reducedImage, (0, ym), (self.originalImage.width, ym), (0, 0, 255)) # B, G, R
        #cv.Line(self.reducedImage, (xm, 0), (xm, self.originalImage.height), (0, 0, 255))

        redColor = (55, 55, 255)
        blueColor = (255, 0, 0)

        orientation = self.markerTracker.orientation
        cv.Circle(self.reducedImage, (xm, ym), 4, redColor, 2)
        xm2 = int(xm + 50*math.cos(orientation))
        ym2 = int(ym + 50*math.sin(orientation))
        cv.Line(self.reducedImage, (xm, ym), (xm2, ym2), blueColor, 2)

        
        xm = xm + self.subImagePosition[0]
        ym = ym + self.subImagePosition[1]
        #print((xm, ym))
        return [xm, ym, orientation]
        
    def showCroppedImage(self):
        pass
        #cv.ShowImage('reducedWindow', self.reducedImage)
        #cv.ShowImage('reducedWindow', self.originalImage)
        #cv.ShowImage('reducedWindow', self.frameGray)
        #cv.ShowImage('reducedWindow', self.markerTracker.frameSumSq)
        
    
    
class CameraDriver:
    ''' 
    Purpose: capture images from a camera and delegate procesing of the 
    images to a different class.
    '''
    def __init__(self, markerOrders = [7, 8], defaultKernelSize = 21, scalingParameter = 2500):
        # Initialize camera driver.
        # Open output window.
        cv.NamedWindow('filterdemo', cv.CV_WINDOW_AUTOSIZE)
        # Select the camera where the images should be grabbed from.
        self.camera = cv.CaptureFromCAM(0)
        # Storage for image processing.
        self.currentFrame = None
        self.processedFrame = None
        self.running = True
        # Storage for trackers.
        self.trackers = []
        self.windowedTrackers = []
        self.oldLocations = []
        # Initialize trackers.
        for markerOrder in markerOrders:
            temp = ImageAnalyzer(1)
            temp.addMarkerToTrack(markerOrder, defaultKernelSize, scalingParameter)
            self.trackers.append(temp)
            self.windowedTrackers.append(TrackerInWindowMode(markerOrder))
            self.oldLocations.append(None)
        self.cnt = 0
        self.defaultOrientation = 0

    
    def getImage(self):
        # Get image from camera.
        self.currentFrame = cv.QueryFrame(self.camera)
        
    def processFrame(self):
        # Locate all markers in image.
        for k in range(len(self.trackers)):
            if(self.oldLocations[k] is None):
                # Previous marker location is unknown, search in the entire image.
                self.processedFrame = self.trackers[k].analyzeImage(self.currentFrame)
                markerX = self.trackers[k].markerLocationsX[0]
                markerY = self.trackers[k].markerLocationsY[0]
                self.oldLocations[k] = [markerX, markerY, self.defaultOrientation]
            else:
                # Search for marker around the old location.
                self.windowedTrackers[k].cropFrame(self.currentFrame, self.oldLocations[k][0], self.oldLocations[k][1])
                self.oldLocations[k] = self.windowedTrackers[k].locateMarker()
                self.windowedTrackers[k].showCroppedImage()
    
    def drawDetectedMarkers(self):
        for k in range(len(self.trackers)):
            xm = self.oldLocations[k][0]
            ym = self.oldLocations[k][1]
            cv.Circle(self.processedFrame, (xm, ym), 4, (55, 55, 255), 2)
            xm2 = xm + 20
            ym2 = ym + 20
            cv.Line(self.processedFrame, (xm, ym), (xm2, ym2), (255, 0, 0), 2)

    
    def showProcessedFrame(self):
        cv.ShowImage('filterdemo', self.processedFrame)
        pass

    def resetAllLocations(self):
        # Reset all markers locations, forcing a full search on the next iteration.
        for k in range(len(self.trackers)):
            self.oldLocations[k] = None
        
    def handleKeyboardEvents(self):
        # Listen for keyboard events and take relevant actions.
        key = cv.WaitKey(20) 
        # Discard higher order bit, http://permalink.gmane.org/gmane.comp.lib.opencv.devel/410
        key = key & 0xff
        if key == 27: # Esc
            self.running = False
        if key == 114: # R
            print("Resetting")
            self.resetAllLocations()
        if key == 115: # S
            # save image
            print("Saving image")
            cv.SaveImage("output/filename%03d.png" % self.cnt, self.currentFrame)
            self.cnt = self.cnt + 1

    def returnPositions(self):
        # Return list of all marker locations.
        return self.oldLocations


class RosPublisher:
    def __init__(self, markers):
        # Instantiate ros publisher with information about the markers that 
        # will be tracked.
        self.pub = []
        self.markers = markers
        for i in markers:
            self.pup.append( rospy.Publisher('positionPuplisher' + str(i), Point)  )       
        rospy.init_node('FrobitLocator')   

    def publishMarkerLocations(self, locations):
        j = 0        
        for i in self.markers:
            print 'x%i %i  y%i %i  o%i %i' %(i, locations[j][0], i, locations[j][1], i, locations[j][2])
            #ros function        
            self.pup[j].publish(  Point( locations[j][0], locations[j][1], locations[j][2] )  )
            j = j + 1                
        

def main():
    
    t0 = time()
    t1 = time()
    t2 = time()

    print 'function vers1 takes %f' %(t1-t0)
    print 'function vers2 takes %f' %(t2-t1)
    
    toFind = [7, 9]    

    if PublishToROS:  
        RP = RosPublisher(toFind)
       
    cd = CameraDriver(toFind)
    t0 = time()
     
    while cd.running:
        (t1, t0) = (t0, time())
      #  print "time for one iteration: %f" % (t0 - t1)
        cd.getImage()
        cd.processFrame()
        #cd.drawDetectedMarkers()
        cd.showProcessedFrame()
        cd.handleKeyboardEvents()
        y = cd.returnPositions()     
        if PublishToROS:
            RP.publishMarkerLocations(y)
        else:
            pass
            #print y
            try:
                print("%3d %3d %8.3f" % (y[0][0], y[0][1], y[0][2]))
            except:
                pass
                
            
    print("Stopping")


main()
