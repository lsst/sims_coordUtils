"""
This unit test compares the outputs of the PALPY driven Astrometry
routines with outputs generated by the same routines powered by
pySLALIB v 1.0.2

There will be some difference, as the two libraries are based on slightly
different conventions (for example, the prenut routine which calculates
the matrix of precession and nutation is based on the IAU 2006A/2000
standard in PALPY and on SF2001 in pySLALIB; however, the two outputs
still agree to within one part in 10^5)

To recreate test data, install pyslalib from

https://git@github.com:/scottransom/pyslalib

include the line

from pyslalib import slalib as sla

at the top of

/lsst/sims/catalogs/measures/astrometry/Astrometry.py

and then replace all occurrences of

pal.medthodName(args)

with

sla.sla_methodName(args)

"""

import numpy

import os
import unittest
import warnings
import sys
import math
import palpy as pal
import lsst.utils.tests as utilsTests

import lsst.afw.geom as afwGeom
from lsst.sims.catalogs.measures.instance import InstanceCatalog
from lsst.sims.catalogs.generation.db import ObservationMetaData, Site
from lsst.sims.coordUtils.Astrometry import AstrometryStars, CameraCoords
from lsst.sims.catalogs.generation.utils import myTestStars, makeStarTestDB
import lsst.afw.cameraGeom.testUtils as camTestUtils


class AstrometryTestStars(myTestStars):
    dbAddress = 'sqlite:///AstrometryTestDatabase.db'

class testCatalog(InstanceCatalog,AstrometryStars,CameraCoords):
    """
    A (somewhat meaningless) instance catalog class that will allow us
    to run the astrometry routines for testing purposes
    """
    catalog_type = 'test_stars'
    column_outputs=['id','raPhoSim','decPhoSim','raObserved','decObserved',
                   'x_focal_nominal', 'y_focal_nominal', 'x_pupil','y_pupil',
                   'chipName', 'xPix', 'yPix','xFocalPlane','yFocalPlane']
    #Needed to do camera coordinate transforms.
    camera = camTestUtils.CameraWrapper().camera
    default_formats = {'f':'%.12f'}

    delimiter = ';' #so that numpy.loadtxt can parse the chipNames which may contain commas
                     #(see testClassMethods)

    default_columns = [('properMotionRa', 0., float),
                       ('properMotionDec', 0., float),
                       ('parallax', 1.2, float),
                       ('radial_velocity', 0., float)]


class astrometryUnitTest(unittest.TestCase):
    """
    The bulk of this unit test involves inputting a set list of input values
    and comparing the astrometric results to results derived from SLALIB run
    with the same input values.  We have to create a test catalog artificially (rather than
    querying the database) because SLALIB was originally run on values that did not correspond
    to any particular Opsim run.
    """
    
    @classmethod
    def setUpClass(cls):
        # Create test databases
        if os.path.exists('AstrometryTestDatabase.db'):
            print "deleting database"
            os.unlink('AstrometryTestDatabase.db')
        makeStarTestDB(filename='AstrometryTestDatabase.db',
                      size=100000, seedVal=1, ramin=199.98*math.pi/180., dra=0.04*math.pi/180.)
    
    def setUp(self):
        self.starDBObject = AstrometryTestStars()
        self.obs_metadata=ObservationMetaData(mjd=50984.371741,
                                     boundType='circle',unrefractedRA=200.0,unrefractedDec=-30.0,
                                     boundLength=0.05)
        self.metadata={}

        #below are metadata values that need to be set in order for
        #get_skyToFocalPlane to work.  If we had been querying the database,
        #these would be set to meaningful values.  Because we are generating
        #an artificial set of inputs that must comport to the baseline SLALIB
        #inputs, these are set arbitrarily by hand
        self.metadata['Unrefracted_RA'] = (200.0, float)
        self.metadata['Unrefracted_Dec'] = (-30.0, float)
        self.metadata['Opsim_rotskypos'] = (1.0, float)

        self.obs_metadata.assignPhoSimMetaData(self.metadata)
        self.cat = testCatalog(self.starDBObject, obs_metadata=self.obs_metadata)
        self.tol=1.0e-5
    
    @classmethod
    def tearDownClass(cls):
        if os.path.exists('AstrometryTestDatabase.db'):
            os.unlink('AstrometryTestDatabase.db')

    def tearDown(self):
        del self.cat
        del self.obs_metadata

    def testWritingOfCatalog(self):
        self.cat.write_catalog("starsTestOutput.txt")

    def testExceptions(self):
        """
        Test to make sure that focal plane methods raise exceptions when coordinates are improperly
        specified.
        """

        #these are just values shown heuristically to give an actual chip name
        ra = numpy.array([numpy.radians(200.0)])
        dec = numpy.array([numpy.radians(-30.0)])
        xPupil = numpy.array([-0.000262243770])
        yPupil = numpy.array([0.000199467792])

        xx, yy = self.cat.calculateFocalPlaneCoordinates(xPupil = xPupil, yPupil = yPupil)
        xx, yy = self.cat.calculateFocalPlaneCoordinates(ra = ra, dec = dec)

        self.assertRaises(RuntimeError, self.cat.calculateFocalPlaneCoordinates)
        self.assertRaises(RuntimeError, self.cat.calculateFocalPlaneCoordinates, ra = ra, dec = dec,
                             xPupil = xPupil, yPupil = yPupil)

        xx, yy = self.cat.calculatePixelCoordinates(xPupil = xPupil, yPupil = yPupil)
        xx, yy = self.cat.calculatePixelCoordinates(ra = ra, dec = dec)

        self.assertRaises(RuntimeError, self.cat.calculatePixelCoordinates)
        self.assertRaises(RuntimeError, self.cat.calculatePixelCoordinates, xPupil = xPupil,
                           yPupil = yPupil, ra = ra, dec = dec)

        name = self.cat.findChipName(xPupil = xPupil, yPupil = yPupil)
        self.assertTrue(name[0] is not None)

        name = self.cat.findChipName(ra = ra, dec = dec)
        self.assertTrue(name[0] is not None)

        self.assertRaises(RuntimeError, self.cat.findChipName)
        self.assertRaises(RuntimeError, self.cat.findChipName, xPupil = xPupil, yPupil = yPupil,
                  ra = ra, dec = dec)

    def testClassMethods(self):
        self.cat.write_catalog("AstrometryTestCatalog.txt")

        dtype = [('id',int),('raPhoSim',float),('decPhoSim',float),('raObserved',float),
                 ('decObserved',float),('x_focal_nominal',float),('y_focal_nominal',float),
                 ('x_pupil',float),('y_pupil',float),('chipName',str,11),('xPix',float),
                 ('yPix',float),('xFocalPlane',float),('yFocalPlane',float)]

        baselineData = numpy.loadtxt('AstrometryTestCatalog.txt',dtype = dtype, delimiter = ';')

        pupilTest = self.cat.calculatePupilCoordinates(baselineData['raObserved'],
                                                 baselineData['decObserved'])

        for (xxtest, yytest, xx, yy) in \
                zip(pupilTest[0], pupilTest[1], baselineData['x_pupil'], baselineData['y_pupil']):
            self.assertAlmostEqual(xxtest,xx,6)
            self.assertAlmostEqual(yytest,yy,6)

        focalTest = self.cat.calculateFocalPlaneCoordinates(xPupil = pupilTest[0],
                                      yPupil = pupilTest[1])

        focalRa = self.cat.calculateFocalPlaneCoordinates(ra = baselineData['raObserved'],
                        dec = baselineData['decObserved'])

        for (xxtest, yytest, xxra, yyra, xx, yy) in \
                zip(focalTest[0], focalTest[1], focalRa[0], focalRa[1],
                        baselineData['xFocalPlane'], baselineData['yFocalPlane']):

            self.assertAlmostEqual(xxtest,xx,6)
            self.assertAlmostEqual(yytest,yy,6)
            self.assertAlmostEqual(xxra,xx,6)
            self.assertAlmostEqual(yyra,yy,6)

        pixTest = self.cat.calculatePixelCoordinates(xPupil = pupilTest[0], yPupil = pupilTest[1])
        pixTestRaDec = self.cat.calculatePixelCoordinates(ra = baselineData['raObserved'],
                                   dec = baselineData['decObserved'])

        for (xxtest, yytest, xxra, yyra, xx, yy) in \
                zip(pixTest[0], pixTest[1], pixTestRaDec[0], pixTestRaDec[1],
                           baselineData['xPix'], baselineData['yPix']):

            if not numpy.isnan(xx) and not numpy.isnan(yy):
                self.assertAlmostEqual(xxtest,xx,6)
                self.assertAlmostEqual(yytest,yy,6)
                self.assertAlmostEqual(xxra,xx,6)
                self.assertAlmostEqual(yyra,yy,6)
            else:
                self.assertTrue(numpy.isnan(xx))
                self.assertTrue(numpy.isnan(yy))
                self.assertTrue(numpy.isnan(xxra))
                self.assertTrue(numpy.isnan(yyra))
                self.assertTrue(numpy.isnan(xxtest))
                self.assertTrue(numpy.isnan(yytest))

        gnomonTest = self.cat.calculateGnomonicProjection(baselineData['raObserved'],
                             baselineData['decObserved'])
        for (xxtest, yytest, xx, yy) in \
                zip(gnomonTest[0], gnomonTest[1],
                    baselineData['x_focal_nominal'], baselineData['y_focal_nominal']):

            self.assertAlmostEqual(xxtest,xx,6)
            self.assertAlmostEqual(yytest,yy,6)

        nameTest = self.cat.findChipName(xPupil = pupilTest[0], yPupil = pupilTest[1])
        nameRA = self.cat.findChipName(ra = baselineData['raObserved'], dec = baselineData['decObserved'])

        for (ntest, nra, ncontrol) in zip(nameTest, nameRA, baselineData['chipName']):
            if ncontrol != 'None':
                self.assertEqual(ntest,ncontrol)
                self.assertEqual(nra,ncontrol)
            else:
                self.assertTrue(ntest is None)
                self.assertTrue(nra is None)

        if os.path.exists("AstrometryTestCatalog.txt"):
            os.unlink("AstrometryTestCatalog.txt")

    def testPassingOfSite(self):
        """
        Test that site information is correctly passed to
        InstanceCatalog objects
        """

        testSite=Site(longitude=10.0,latitude=20.0,height=4000.0, \
              xPolar=2.4, yPolar=1.4, meanTemperature=314.0, \
              meanPressure=800.0,meanHumidity=0.9, lapseRate=0.01)

        obs_metadata=ObservationMetaData(mjd=50984.371741,boundType='circle',unrefractedRA=200.0,
                                         unrefractedDec=-30.0,boundLength=0.05,site=testSite)
        metadata={}

        #below are metadata values that need to be set in order for
        #get_skyToFocalPlane to work.  If we had been querying the database,
        #these would be set to meaningful values.  Because we are generating
        #an artificial set of inputs that must comport to the baseline SLALIB
        #inputs, these are set arbitrarily by hand
        metadata['Unrefracted_RA'] = (200.0, float)
        metadata['Unrefracted_Dec'] = (-30.0, float)
        metadata['Opsim_rotskypos'] = (1.0, float)

        obs_metadata.assignPhoSimMetaData(metadata)

        cat2=testCatalog(self.starDBObject,obs_metadata=obs_metadata)

        self.assertEqual(cat2.site.longitude,10.0)
        self.assertEqual(cat2.site.latitude,20.0)
        self.assertEqual(cat2.site.height,4000.0)
        self.assertEqual(cat2.site.xPolar,2.4)
        self.assertEqual(cat2.site.yPolar,1.4)
        self.assertEqual(cat2.site.meanTemperature,314.0)
        self.assertEqual(cat2.site.meanPressure,800.0)
        self.assertEqual(cat2.site.meanHumidity,0.9)
        self.assertEqual(cat2.site.lapseRate,0.01)

    def testSphericalToCartesian(self):
        arg1=2.19911485751
        arg2=5.96902604182
        output=self.cat.sphericalToCartesian(arg1,arg2)

        vv=numpy.zeros((3),dtype=float)
        vv[0]=numpy.cos(arg2)*numpy.cos(arg1)
        vv[1]=numpy.cos(arg2)*numpy.sin(arg1)
        vv[2]=numpy.sin(arg2)

        self.assertAlmostEqual(output[0],vv[0],7)
        self.assertAlmostEqual(output[1],vv[1],7)
        self.assertAlmostEqual(output[2],vv[2],7)

    def testCartesianToSpherical(self):
        """
        Note that xyz[i][j] is the ith component of the jth vector

        Each column of xyz is a vector
        """
        xyz=numpy.zeros((3,3),dtype=float)

        xyz[0][0]=-1.528397655830016078e-03
        xyz[0][1]=-1.220314328441649110e+00
        xyz[0][2]=-1.209496845057127512e+00
        xyz[1][0]=-2.015391452804179195e+00
        xyz[1][1]=3.209255728096233051e-01
        xyz[1][2]=-2.420049632697228503e+00
        xyz[2][0]=-1.737023855580406284e+00
        xyz[2][1]=-9.876134719050078115e-02
        xyz[2][2]=-2.000636201137401038e+00

        output=self.cat.cartesianToSpherical(xyz)

        vv=numpy.zeros((3),dtype=float)

        for i in range(3):

            rr=numpy.sqrt(xyz[0][i]*xyz[0][i]+xyz[1][i]*xyz[1][i]+xyz[2][i]*xyz[2][i])

            vv[0]=rr*numpy.cos(output[1][i])*numpy.cos(output[0][i])
            vv[1]=rr*numpy.cos(output[1][i])*numpy.sin(output[0][i])
            vv[2]=rr*numpy.sin(output[1][i])

            for j in range(3):
                self.assertAlmostEqual(vv[j],xyz[j][i],7)


    def testAngularSeparation(self):
        arg1 = 7.853981633974482790e-01
        arg2 = 3.769911184307751517e-01
        arg3 = 5.026548245743668986e+00
        arg4 = -6.283185307179586232e-01

        output=self.cat.angularSeparation(arg1,arg2,arg3,arg4)

        self.assertAlmostEqual(output,2.162615946398791955e+00,10)

    def testRotationMatrixFromVectors(self):
        v1=numpy.zeros((3),dtype=float)
        v2=numpy.zeros((3),dtype=float)
        v3=numpy.zeros((3),dtype=float)

        v1[0]=-3.044619987218469825e-01
        v2[0]=5.982190522311925385e-01
        v1[1]=-5.473550908956383854e-01
        v2[1]=-5.573565912346714057e-01
        v1[2]=7.795545496018386755e-01
        v2[2]=-5.757495946632366079e-01

        output=self.cat.rotationMatrixFromVectors(v1,v2)

        for i in range(3):
            for j in range(3):
                v3[i]+=output[i][j]*v1[j]

        for i in range(3):
            self.assertAlmostEqual(v3[i],v2[i],7)

    def testApplyPrecession(self):

        ra=numpy.zeros((3),dtype=float)
        dec=numpy.zeros((3),dtype=float)

        ra[0]=2.549091039839124218e+00
        dec[0]=5.198752733024248895e-01
        ra[1]=8.693375673649429425e-01
        dec[1]=1.038086165642298164e+00
        ra[2]=7.740864769302191473e-01
        dec[2]=2.758053025017753179e-01

        #the MJD kwarg in applyPrecession below is a hold-over from
        #a misunderstanding in the API for the pal.prenut() back
        #when we generated the test data
        output=self.cat.applyPrecession(ra,dec, MJD=pal.epj(2000.0))

        self.assertAlmostEqual(output[0][0],2.514361575034799401e+00,6)
        self.assertAlmostEqual(output[1][0], 5.306722463159389003e-01,6)
        self.assertAlmostEqual(output[0][1],8.224493314855578774e-01,6)
        self.assertAlmostEqual(output[1][1],1.029318353760459104e+00,6)
        self.assertAlmostEqual(output[0][2],7.412362765815005972e-01,6)
        self.assertAlmostEqual(output[1][2],2.662034339930458571e-01,6)

    def testApplyProperMotion(self):

        ra=numpy.zeros((3),dtype=float)
        dec=numpy.zeros((3),dtype=float)
        pm_ra=numpy.zeros((3),dtype=float)
        pm_dec=numpy.zeros((3),dtype=float)
        parallax=numpy.zeros((3),dtype=float)
        v_rad=numpy.zeros((3),dtype=float)

        ra[0]=2.549091039839124218e+00
        dec[0]=5.198752733024248895e-01
        pm_ra[0]=-8.472633255615005918e-05
        pm_dec[0]=-5.618517146980475171e-07
        parallax[0]=9.328946209650547383e-02
        v_rad[0]=3.060308412186171267e+02

        ra[1]=8.693375673649429425e-01
        dec[1]=1.038086165642298164e+00
        pm_ra[1]=-5.848962163813087908e-05
        pm_dec[1]=-3.000346282603337522e-05
        parallax[1]=5.392364722571952457e-02
        v_rad[1]=4.785834687356999098e+02

        ra[2]=7.740864769302191473e-01
        dec[2]=2.758053025017753179e-01
        pm_ra[2]=5.904070507320858615e-07
        pm_dec[2]=-2.958381482198743105e-05
        parallax[2]=2.172865273161764255e-02
        v_rad[2]=-3.225459751425886452e+02

        ep=2.001040286039033845e+03
        mjd=2.018749109074271473e+03
        obs_metadata=ObservationMetaData(mjd=mjd,
                                     boundType='circle',unrefractedRA=200.0,unrefractedDec=-30.0,
                                     boundLength=0.05)

        obs_metadata.assignPhoSimMetaData(self.metadata)
        cat = testCatalog(self.starDBObject, obs_metadata=obs_metadata)

        output=cat.applyProperMotion(ra,dec,pm_ra,pm_dec,parallax,v_rad,EP0=ep)

        self.assertAlmostEqual(output[0][0],2.549309127917495754e+00,6)
        self.assertAlmostEqual(output[1][0],5.198769294314042888e-01,6)
        self.assertAlmostEqual(output[0][1],8.694881589882680339e-01,6)
        self.assertAlmostEqual(output[1][1],1.038238225568303363e+00,6)
        self.assertAlmostEqual(output[0][2],7.740849573146946216e-01,6)
        self.assertAlmostEqual(output[1][2],2.758844356561930278e-01,6)

    def testEquatorialToGalactic(self):

        ra=numpy.zeros((3),dtype=float)
        dec=numpy.zeros((3),dtype=float)

        ra[0]=2.549091039839124218e+00
        dec[0]=5.198752733024248895e-01
        ra[1]=8.693375673649429425e-01
        dec[1]=1.038086165642298164e+00
        ra[2]=7.740864769302191473e-01
        dec[2]=2.758053025017753179e-01

        output=self.cat.equatorialToGalactic(ra,dec)

        self.assertAlmostEqual(output[0][0],3.452036693523627964e+00,6)
        self.assertAlmostEqual(output[1][0],8.559512505657201897e-01,6)
        self.assertAlmostEqual(output[0][1],2.455968474619387720e+00,6)
        self.assertAlmostEqual(output[1][1],3.158563770667878468e-02,6)
        self.assertAlmostEqual(output[0][2],2.829585540991265358e+00,6)
        self.assertAlmostEqual(output[1][2],-6.510790587552289788e-01,6)


    def testGalacticToEquatorial(self):

        lon=numpy.zeros((3),dtype=float)
        lat=numpy.zeros((3),dtype=float)

        lon[0]=3.452036693523627964e+00
        lat[0]=8.559512505657201897e-01
        lon[1]=2.455968474619387720e+00
        lat[1]=3.158563770667878468e-02
        lon[2]=2.829585540991265358e+00
        lat[2]=-6.510790587552289788e-01

        output=self.cat.galacticToEquatorial(lon,lat)

        self.assertAlmostEqual(output[0][0],2.549091039839124218e+00,6)
        self.assertAlmostEqual(output[1][0],5.198752733024248895e-01,6)
        self.assertAlmostEqual(output[0][1],8.693375673649429425e-01,6)
        self.assertAlmostEqual(output[1][1],1.038086165642298164e+00,6)
        self.assertAlmostEqual(output[0][2],7.740864769302191473e-01,6)
        self.assertAlmostEqual(output[1][2],2.758053025017753179e-01,6)

    def testApplyMeanApparentPlace(self):
        ra=numpy.zeros((3),dtype=float)
        dec=numpy.zeros((3),dtype=float)
        pm_ra=numpy.zeros((3),dtype=float)
        pm_dec=numpy.zeros((3),dtype=float)
        parallax=numpy.zeros((3),dtype=float)
        v_rad=numpy.zeros((3),dtype=float)


        ra[0]=2.549091039839124218e+00
        dec[0]=5.198752733024248895e-01
        pm_ra[0]=-8.472633255615005918e-05
        pm_dec[0]=-5.618517146980475171e-07
        parallax[0]=9.328946209650547383e-02
        v_rad[0]=3.060308412186171267e+02

        ra[1]=8.693375673649429425e-01
        dec[1]=1.038086165642298164e+00
        pm_ra[1]=-5.848962163813087908e-05
        pm_dec[1]=-3.000346282603337522e-05
        parallax[1]=5.392364722571952457e-02
        v_rad[1]=4.785834687356999098e+02

        ra[2]=7.740864769302191473e-01
        dec[2]=2.758053025017753179e-01
        pm_ra[2]=5.904070507320858615e-07
        pm_dec[2]=-2.958381482198743105e-05
        parallax[2]=2.172865273161764255e-02
        v_rad[2]=-3.225459751425886452e+02


        #hack because this is how the SLALIB baseline tests were run
        for i in range(3):
            pm_dec[i]=pm_dec[i]/numpy.cos(dec[i])

        ep=2.001040286039033845e+03
        mjd=2.018749109074271473e+03
        obs_metadata=ObservationMetaData(mjd=mjd,
                                     boundType='circle',unrefractedRA=200.0,unrefractedDec=-30.0,
                                     boundLength=0.05)

        obs_metadata.assignPhoSimMetaData(self.metadata)
        cat = testCatalog(self.starDBObject, obs_metadata=obs_metadata)

        output=cat.applyMeanApparentPlace(ra,dec,pm_ra = pm_ra,pm_dec = pm_dec,
              parallax = parallax,v_rad = v_rad, Epoch0=ep)

        self.assertAlmostEqual(output[0][0],2.525858337335585180e+00,6)
        self.assertAlmostEqual(output[1][0],5.309044018653210628e-01,6)
        self.assertAlmostEqual(output[0][1],8.297492370691380570e-01,6)
        self.assertAlmostEqual(output[1][1],1.037400063009288331e+00,6)
        self.assertAlmostEqual(output[0][2],7.408639821342507537e-01,6)
        self.assertAlmostEqual(output[1][2],2.703229189890907214e-01,6)

    def testApplyMeanObservedPlace(self):
        """
        Note: this routine depends on Aopqk which fails if zenith distance
        is too great (or, at least, it won't warn you if the zenith distance
        is greater than pi/2, in which case answers won't make sense)
        """

        ra=numpy.zeros((3),dtype=float)
        dec=numpy.zeros((3),dtype=float)
        wv = 5000.0

        ra[0]=2.549091039839124218e+00
        dec[0]=5.198752733024248895e-01
        ra[1]=4.346687836824714712e-01
        dec[1]=-5.190430828211490821e-01
        ra[2]=7.740864769302191473e-01
        dec[2]=2.758053025017753179e-01

        mjd=2.018749109074271473e+03
        obs_metadata=ObservationMetaData(mjd=mjd,
                                     boundType='circle',unrefractedRA=200.0,unrefractedDec=-30.0,
                                     boundLength=0.05)

        obs_metadata.assignPhoSimMetaData(self.metadata)
        cat = testCatalog(self.starDBObject, obs_metadata=obs_metadata)

        output=cat.applyMeanObservedPlace(ra,dec, wavelength=wv)

        self.assertAlmostEqual(output[0][0],2.547475965605183745e+00,6)
        self.assertAlmostEqual(output[1][0],5.187045152602967057e-01,6)

        self.assertAlmostEqual(output[0][1],4.349858626308809040e-01,6)
        self.assertAlmostEqual(output[1][1],-5.191213875880701378e-01,6)

        self.assertAlmostEqual(output[0][2],7.743528611421227614e-01,6)
        self.assertAlmostEqual(output[1][2],2.755070101670137328e-01,6)
        
        output=self.cat.applyMeanObservedPlace(ra,dec,altAzHr=True, wavelength=wv)
        
        self.assertAlmostEqual(output[0][0],2.547475965605183745e+00,6)
        self.assertAlmostEqual(output[1][0],5.187045152602967057e-01,6)
        self.assertAlmostEqual(output[2][0],1.168920017932007643e-01,6)
        self.assertAlmostEqual(output[3][0],8.745379535264000692e-01,6)

        self.assertAlmostEqual(output[0][1],4.349858626308809040e-01,6)
        self.assertAlmostEqual(output[1][1],-5.191213875880701378e-01,6)
        self.assertAlmostEqual(output[2][1],6.766119585479937193e-01,6)
        self.assertAlmostEqual(output[3][1],4.433969998336554141e+00,6)

        self.assertAlmostEqual(output[0][2],7.743528611421227614e-01,6)
        self.assertAlmostEqual(output[1][2],2.755070101670137328e-01,6)
        self.assertAlmostEqual(output[2][2],5.275840601437552513e-01,6)
        self.assertAlmostEqual(output[3][2],5.479759580847959555e+00,6)

        output=self.cat.applyMeanObservedPlace(ra,dec,includeRefraction=False,
                                               wavelength=wv)

        self.assertAlmostEqual(output[0][0],2.549091783674975353e+00,6)
        self.assertAlmostEqual(output[1][0],5.198746844679964507e-01,6)

        self.assertAlmostEqual(output[0][1],4.346695674418772359e-01,6)
        self.assertAlmostEqual(output[1][1],-5.190436610150490626e-01,6)

        self.assertAlmostEqual(output[0][2],7.740875471580924705e-01,6)
        self.assertAlmostEqual(output[1][2],2.758055401087299296e-01,6)

        output=self.cat.applyMeanObservedPlace(ra,dec,includeRefraction=False,
                                               altAzHr=True, wavelength=wv)

        self.assertAlmostEqual(output[0][0],2.549091783674975353e+00,6)
        self.assertAlmostEqual(output[1][0],5.198746844679964507e-01,6)
        self.assertAlmostEqual(output[2][0],1.150652107618796299e-01,6)
        self.assertAlmostEqual(output[3][0],8.745379535264000692e-01,6)

        self.assertAlmostEqual(output[0][1],4.346695674418772359e-01,6)
        self.assertAlmostEqual(output[1][1],-5.190436610150490626e-01,6)
        self.assertAlmostEqual(output[2][1],6.763265401447272618e-01,6)
        self.assertAlmostEqual(output[3][1],4.433969998336554141e+00,6)

        self.assertAlmostEqual(output[0][2],7.740875471580924705e-01,6)
        self.assertAlmostEqual(output[1][2],2.758055401087299296e-01,6)
        self.assertAlmostEqual(output[2][2],5.271912536356709866e-01,6)
        self.assertAlmostEqual(output[3][2],5.479759580847959555e+00,6)


    def testMeanObservedPlace_NoRefraction(self):

        ra=numpy.zeros((3),dtype=float)
        dec=numpy.zeros((3),dtype=float)

        ra[0]=2.549091039839124218e+00
        dec[0]=5.198752733024248895e-01
        ra[1]=4.346687836824714712e-01
        dec[1]=-5.190430828211490821e-01
        ra[2]=7.740864769302191473e-01
        dec[2]=2.758053025017753179e-01

        mjd=2.018749109074271473e+03
        obs_metadata=ObservationMetaData(mjd=mjd,
                                     boundType='circle',unrefractedRA=200.0,unrefractedDec=-30.0,
                                     boundLength=0.05)
        metadata={}
        metadata['Unrefracted_RA'] = (200.0, float)
        metadata['Unrefracted_Dec'] = (-30.0, float)
        metadata['Opsim_rotskypos'] = (1.0, float)

        obs_metadata.assignPhoSimMetaData(metadata)
        cat = testCatalog(self.starDBObject, obs_metadata=obs_metadata)
 
        output=cat.applyMeanObservedPlace(ra,dec,altAzHr=True,
                 includeRefraction = False)

        self.assertAlmostEqual(output[0][0],2.549091783674975353e+00,6)
        self.assertAlmostEqual(output[1][0],5.198746844679964507e-01,6)
        self.assertAlmostEqual(output[0][1],4.346695674418772359e-01,6)
        self.assertAlmostEqual(output[1][1],-5.190436610150490626e-01,6)
        self.assertAlmostEqual(output[0][2],7.740875471580924705e-01,6)
        self.assertAlmostEqual(output[1][2],2.758055401087299296e-01,6)
        self.assertAlmostEqual(output[2][2],5.271914342095551653e-01,6)
        self.assertAlmostEqual(output[3][2],5.479759402150099490e+00,6)

    def testRefractionCoefficients(self):
        output=self.cat.refractionCoefficients(wavelength=5000.0)

        self.assertAlmostEqual(output[0],2.295817926320665320e-04,6)
        self.assertAlmostEqual(output[1],-2.385964632924575670e-07,6)

    def testApplyRefraction(self):
        coeffs=self.cat.refractionCoefficients(wavelength = 5000.0)

        output=self.cat.applyRefraction(0.25*numpy.pi,coeffs[0],coeffs[1])

        self.assertAlmostEqual(output,7.851689251070859132e-01,6)

    def testCalcLast(self):

        arg1=2.004031374869656474e+03
        arg2=10

        output=self.cat.calcLast(arg1,arg2)
        self.assertAlmostEqual(output,1.662978602873423029e+00,5)

    def testEquatorialToHorizontal(self):
        arg1=2.549091039839124218e+00
        arg2=5.198752733024248895e-01
        arg3=2.004031374869656474e+03
        output=self.cat.equatorialToHorizontal(arg1,arg2,arg3)

        self.assertAlmostEqual(output[0],4.486633480937949336e-01,5)
        self.assertAlmostEqual(output[1],5.852620488358430961e+00,5)

    def testParalacticAngle(self):
        arg1=1.507444663929565554e+00
        arg2=-4.887258694875344922e-01

        output=self.cat.paralacticAngle(arg1,arg2)

        self.assertAlmostEqual(output,1.381600229503358701e+00,6)

    def testPixelPos(self):
        for chunk, chunkMap in self.cat.iter_catalog_chunks():
            self.assertTrue(numpy.all(numpy.isfinite(self.cat.column_by_name('x_pupil'))))
            self.assertTrue(numpy.all(numpy.isfinite(self.cat.column_by_name('y_pupil'))))
            for x, y, cname in zip(self.cat.column_by_name('xPix'), self.cat.column_by_name('yPix'),
                                   self.cat.column_by_name('chipName')):
                if cname is None:
                    #make sure that x and y are not set if the object doesn't land on a chip
                    self.assertTrue(not numpy.isfinite(x) and not numpy.isfinite(y))
                else:
                    #make sure the pixel positions are inside the detector bounding box.
                    self.assertTrue(afwGeom.Box2D(self.cat.camera[cname].getBBox()).contains(afwGeom.Point2D(x,y)))

def suite():
    utilsTests.init()
    suites = []
    suites += unittest.makeSuite(astrometryUnitTest)
    return unittest.TestSuite(suites)

def run(shouldExit = False):
    utilsTests.run(suite(),shouldExit)

if __name__ == "__main__":
    run(True)
