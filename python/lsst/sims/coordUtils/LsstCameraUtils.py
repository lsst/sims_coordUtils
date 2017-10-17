from __future__ import division
from builtins import zip
from builtins import str
from builtins import range
import numpy as np
import lsst.afw.geom as afwGeom
from lsst.afw.cameraGeom import FIELD_ANGLE, FOCAL_PLANE, PIXELS, WAVEFRONT
from lsst.afw.geom import Box2D
from lsst.sims.coordUtils import pupilCoordsFromPixelCoords, pixelCoordsFromPupilCoords
from lsst.sims.utils import _pupilCoordsFromRaDec
from lsst.sims.coordUtils import getCornerPixels, _validate_inputs_and_chipname
from lsst.sims.utils.CodeUtilities import _validate_inputs
from lsst.obs.lsstSim import LsstSimMapper
from lsst.sims.utils import radiansFromArcsec

import time

__all__ = ["lsst_camera", "chipNameFromPupilCoordsLSST",
           "_chipNameFromRaDecLSST", "chipNameFromRaDecLSST",
           "_pixelCoordsFromRaDecLSST", "pixelCoordsFromRaDecLSST"]


def lsst_camera():
    """
    Return a copy of the LSST Camera model as stored in obs_lsstSim.
    """
    if not hasattr(lsst_camera, '_lsst_camera'):
        lsst_camera._lsst_camera = LsstSimMapper().camera

    return lsst_camera._lsst_camera


def _build_lsst_pupil_coord_map():
    """
    Build a map of pupil coordinates on the LSST focal plane.
    Returns _lsst_pupil_coord_map, which is a dict.
    _lsst_pupil_coord_map['name'] contains a list of the names of each chip in the lsst camera
    _lsst_pupil_coord_map['xx'] contains the x pupil coordinate of the center of each chip
    _lsst_pupil_coord_map['yy'] contains the y pupil coordinate of the center of each chip
    _lsst_pupil_coord_map['dp'] contains the radius (in pupil coordinates) of the circle containing each chip
    """

    name_list = []
    x_pix_list = []
    y_pix_list = []
    n_chips = 0
    for chip in lsst_camera():
        chip_name = chip.getName()
        n_chips += 1
        corner_list = getCornerPixels(chip_name, lsst_camera())
        for corner in corner_list:
            x_pix_list.append(corner[0])
            y_pix_list.append(corner[1])
            name_list.append(chip_name)

    x_pix_list = np.array(x_pix_list)
    y_pix_list = np.array(y_pix_list)

    x_pup_list, y_pup_list = pupilCoordsFromPixelCoords(x_pix_list,
                                                        y_pix_list,
                                                        name_list,
                                                        camera=lsst_camera())
    center_x = np.zeros(n_chips, dtype=float)
    center_y = np.zeros(n_chips, dtype=float)
    extent = np.zeros(n_chips, dtype=float)
    final_name = []
    for ix_ct in range(n_chips):
        ix = ix_ct*4
        chip_name = name_list[ix]
        xx = 0.25*(x_pup_list[ix] + x_pup_list[ix+1] +
                   x_pup_list[ix+2] + x_pup_list[ix+3])

        yy = 0.25*(y_pup_list[ix] + y_pup_list[ix+1] +
                   y_pup_list[ix+2] + y_pup_list[ix+3])

        dx = 0.25*np.array([np.sqrt(np.power(xx-x_pup_list[ix+ii], 2) +
                                    np.power(yy-y_pup_list[ix+ii], 2)) for ii in range(4)]).sum()

        center_x[ix_ct] = xx
        center_y[ix_ct] = yy
        extent[ix_ct] = dx
        final_name.append(chip_name)

    final_name = np.array(final_name)

    lsst_pupil_coord_map = {}
    lsst_pupil_coord_map['name'] = final_name
    lsst_pupil_coord_map['xx'] = center_x
    lsst_pupil_coord_map['yy'] = center_y
    lsst_pupil_coord_map['dp'] = extent
    return lsst_pupil_coord_map


def _findDetectorsListLSST(pupilPointList, detectorList, allow_multiple_chips=False):
    """!Find the detectors that cover a list of points specified by x and y coordinates in any system

    This is based one afw.camerGeom.camera.findDetectorsList.  It has been optimized for the LSST
    camera in the following way:

        - it accepts a limited list of detectors to check in advance (this list should be
          constructed by comparing the pupil coordinates in question and comparing to the
          pupil coordinates of the center of each detector)

       - it will stop looping through detectors one it has found one that is correct (the LSST
         camera does not allow an object to fall on more than one detector)

    @param[in] pupilPointList  a list of points in PUPIL/FIELD_ANGLE coordinates

    @param[in] detecorList is a list of lists.  Each row contains the detectors that should be searched
    for the correspdonding pupilPoint

    @param [in] allow_multiple_chips is a boolean (default False) indicating whether or not
    this method will allow objects to be visible on more than one chip.  If it is 'False'
    and an object appears on more than one chip, only the first chip will appear in the list of
    chipNames but NO WARNING WILL BE EMITTED.  If it is 'True' and an object falls on more than one
    chip, a list of chipNames will appear for that object.

    @return outputNameList is a numpy array of the names of the detectors
    """

    # transform the points to the native coordinate system
    #
    # The conversion to a numpy array looks a little clunky.
    # The problem, if you do the naive thing (nativePointList = np.array(lsst_camera().....),
    # the conversion to a numpy array gets passed down to the contents of nativePointList
    # and they end up in a form that the afwCameraGeom code does not know how to handle
    nativePointList = np.zeros(len(pupilPointList), dtype=object)
    nativePointList_raw = lsst_camera()._transformSingleSysArray(pupilPointList, FIELD_ANGLE,
                                                                 lsst_camera()._nativeCameraSys)
    for i_nn in range(len(nativePointList_raw)):
        nativePointList[i_nn] = nativePointList_raw[i_nn]

    # initialize output and some caching lists
    outputNameList = [None]*len(pupilPointList)
    chip_has_found = np.array([-1]*len(pupilPointList))
    for i_pt, det_list in enumerate(detectorList):
        if len(det_list) == 0:
            chip_has_found[i_pt] = 1  # no need to search chips with no candidates

    checked_detectors = []

    # Figure out if any of these (RA, Dec) pairs could be
    # on more than one chip.  This is possible on the
    # wavefront sensors, since adjoining wavefront sensors
    # are kept one in focus, one out of focus.
    # See figure 2 of arXiv:1506.04839v2
    # (This might actually be a bug in obs_lsstSim
    # I opened DM-8075 on 25 October 2016 to investigate)
    could_be_multiple = [False]*len(pupilPointList)
    if allow_multiple_chips:
        for ipt in range(len(pupilPointList)):
            for det in detectorList[ipt]:
                if det.getType() == WAVEFRONT:
                    could_be_multiple[ipt] = True

    update_unfound = True

    t_assemble_list = 0.0

    # loop over (RA, Dec) pairs
    for ipt, nativePoint in enumerate(nativePointList):
        if chip_has_found[ipt] < 0:  # i.e. if we have not yet found this (RA, Dec) pair
            for detector in detectorList[ipt]:

                # check that we have not already considered this detector
                if detector not in checked_detectors:
                    checked_detectors.append(detector)

                    # in order to avoid constantly re-instantiating the same afwCameraGeom detector,
                    # we will now find all of the (RA, Dec) pairs that could be on the present
                    # chip and test them.
                    if update_unfound:
                        unfound_pts = np.where(chip_has_found < 0)[0]
                        update_unfound = False

                    if len(unfound_pts) == 0:
                        # we have already found all of the (RA, Dec) pairs
                        for ix, name in enumerate(outputNameList):
                            if isinstance(name, list):
                                outputNameList[ix] = str(name)
                        return np.array(outputNameList)

                    t_before_assemble = time.time()
                    valid_pt_dexes = np.array([ii for ii in unfound_pts if detector in detectorList[ii]])
                    t_assemble_list += time.time()-t_before_assemble
                    if len(valid_pt_dexes) > 0:
                        valid_pt_list = nativePointList[valid_pt_dexes]
                        transform = detector.getTransform(lsst_camera()._nativeCameraSys, PIXELS)
                        detectorPointList = transform.applyForward(valid_pt_list)

                        box = afwGeom.Box2D(detector.getBBox())
                        for ix, pt in zip(valid_pt_dexes, detectorPointList):
                            if box.contains(pt):
                                if not could_be_multiple[ix]:
                                    # because this (RA, Dec) pair is not marked as could_be_multiple,
                                    # the fact that this (RA, Dec) pair is on the current chip
                                    # means this (RA, Dec) pair no longer needs to be considered.
                                    # You can set chip_has_found[ix] to unity.
                                    outputNameList[ix] = detector.getName()
                                    chip_has_found[ix] = 1
                                    update_unfound = True
                                else:
                                    # Since this (RA, Dec) pair has been makred could_be_multiple,
                                    # finding this (RA, Dec) pair on the chip does not remove the
                                    # (RA, Dec) pair from contention.
                                    if outputNameList[ix] is None:
                                        outputNameList[ix] = detector.getName()
                                    elif isinstance(outputNameList[ix], list):
                                        outputNameList[ix].append(detector.getName())
                                    else:
                                        outputNameList[ix] = [outputNameList[ix], detector.getName()]

    # convert entries corresponding to multiple chips into strings
    # (i.e. [R:2,2 S:0,0, R:2,2 S:0,1] becomes `[R:2,2 S:0,0, R:2,2 S:0,1]`)
    for ix, name in enumerate(outputNameList):
        if isinstance(name, list):
            outputNameList[ix] = str(name)

    print('t_assemble %.2e' % t_assemble_list)

    return np.array(outputNameList)


def chipNameFromPupilCoordsLSST(xPupil, yPupil, allow_multiple_chips=False):
    """
    Return the names of LSST detectors that see the object specified by
    either (xPupil, yPupil).

    @param [in] xPupil is the x pupil coordinate in radians.
    Must be a numpy array.

    @param [in] yPupil is the y pupil coordinate in radians.
    Must be a numpy array.

    @param [in] allow_multiple_chips is a boolean (default False) indicating whether or not
    this method will allow objects to be visible on more than one chip.  If it is 'False'
    and an object appears on more than one chip, only the first chip will appear in the list of
    chipNames and warning will be emitted.  If it is 'True' and an object falls on more than one
    chip, a list of chipNames will appear for that object.

    @param [out] a numpy array of chip names

    """
    t_start = time.time()
    if (not hasattr(chipNameFromPupilCoordsLSST, '_pupil_map') or
    not hasattr(chipNameFromPupilCoordsLSST, '_detector_arr') or
    len(chipNameFromPupilCoordsLSST._detector_arr) == 0):
        pupil_map = _build_lsst_pupil_coord_map()
        chipNameFromPupilCoordsLSST._pupil_map = pupil_map
        camera = lsst_camera()
        detector_arr = np.zeros(len(pupil_map['name']), dtype=object)
        for ii in range(len(pupil_map['name'])):
            detector_arr[ii] = camera[pupil_map['name'][ii]]

        chipNameFromPupilCoordsLSST._detector_arr = detector_arr

        # build a Box2D that contains all of the detectors in the camera
        focal_to_field = camera.getTransformMap().getTransform(FOCAL_PLANE, FIELD_ANGLE)
        focal_bbox = camera.getFpBBox()
        focal_corners = focal_bbox.getCorners()
        pupil_corners = focal_to_field.applyForward(focal_corners)
        camera_bbox = Box2D()
        for cc in pupil_corners:
            camera_bbox.include(cc)
        chipNameFromPupilCoordsLSST._camera_bbox = camera_bbox

    are_arrays = _validate_inputs([xPupil, yPupil], ['xPupil', 'yPupil'], "chipNameFromPupilCoordsLSST")

    if not are_arrays:
        xPupil = np.array([xPupil])
        yPupil = np.array([yPupil])

    pupilPointList = [afwGeom.Point2D(x, y) for x, y in zip(xPupil, yPupil)]

    # filter out those points that are not inside the
    # camera-containing Box2D
    is_okay = np.array([False]*len(pupilPointList))
    for i_pp, pp in enumerate(pupilPointList):
        if chipNameFromPupilCoordsLSST._camera_bbox.contains(pp):
            is_okay[i_pp] = True

    # Loop through every point being considered.  For each point, assemble a list of detectors
    # whose centers are within 1.1 detector radii of the point.  These are the detectors on which
    # the point could be located.  Store that list of possible detectors as a row in valid_detctors,
    # which will be passed to _findDetectorsListLSST()
    t_before_guess = time.time()
    t_where = 0.0
    valid_detectors = []
    x_cam = chipNameFromPupilCoordsLSST._pupil_map['xx']
    y_cam = chipNameFromPupilCoordsLSST._pupil_map['yy']
    rrsq_lim = (1.1*chipNameFromPupilCoordsLSST._pupil_map['dp'])**2
    for i_pp, (xx, yy) in enumerate(zip(xPupil, yPupil)):
        if not is_okay[i_pp]:
            valid_detectors.append([])
            continue

        t_before_where = time.time()
        possible_dexes = np.where(((xx-x_cam)**2 + (yy-y_cam)**2) < rrsq_lim)
        t_where += time.time()-t_before_where

        local_valid = chipNameFromPupilCoordsLSST._detector_arr[possible_dexes]
        valid_detectors.append(list(local_valid))
    t_guess = time.time()-t_before_guess

    t_before_find = time.time()
    nameList = _findDetectorsListLSST(pupilPointList, valid_detectors,
                                      allow_multiple_chips=allow_multiple_chips)
    t_find = time.time()-t_before_find

    print('chipNameFromPupil %.2e percapita %.2e' % ((time.time()-t_start), (time.time()-t_start)/float(len(xPupil))))
    print('t_guess %.2e' % t_guess)
    print('t_where %.2e' % t_where)
    print('t_find %.2e' % t_find)
    print('\n')
    return nameList


def _chipNameFromRaDecLSST(ra, dec, pm_ra=None, pm_dec=None, parallax=None, v_rad=None,
                           obs_metadata=None, epoch=2000.0, allow_multiple_chips=False):
    """
    Return the names of detectors on the LSST camera that see the object specified by
    (RA, Dec) in radians.

    @param [in] ra in radians (a numpy array or a float).
    In the International Celestial Reference System.

    @param [in] dec in radians (a numpy array or a float).
    In the International Celestial Reference System.

    @param [in] pm_ra is proper motion in RA multiplied by cos(Dec) (radians/yr)
    Can be a numpy array or a number or None (default=None).

    @param [in] pm_dec is proper motion in dec (radians/yr)
    Can be a numpy array or a number or None (default=None).

    @param [in] parallax is parallax in radians
    Can be a numpy array or a number or None (default=None).

    @param [in] v_rad is radial velocity (km/s)
    Can be a numpy array or a number or None (default=None).

    @param [in] obs_metadata is an ObservationMetaData characterizing the telescope pointing

    @param [in] epoch is the epoch in Julian years of the equinox against which RA and Dec are
    measured.  Default is 2000.

    @param [in] allow_multiple_chips is a boolean (default False) indicating whether or not
    this method will allow objects to be visible on more than one chip.  If it is 'False'
    and an object appears on more than one chip, only the first chip will appear in the list of
    chipNames but NO WARNING WILL BE EMITTED.  If it is 'True' and an object falls on more than one
    chip, a list of chipNames will appear for that object.

    @param [out] the name(s) of the chips on which ra, dec fall (will be a numpy
    array if more than one)
    """

    are_arrays = _validate_inputs([ra, dec], ['ra', 'dec'], "chipNameFromRaDecLSST")

    if epoch is None:
        raise RuntimeError("You need to pass an epoch into chipName")

    if obs_metadata is None:
        raise RuntimeError("You need to pass an ObservationMetaData into chipName")

    if obs_metadata.mjd is None:
        raise RuntimeError("You need to pass an ObservationMetaData with an mjd into chipName")

    if obs_metadata.rotSkyPos is None:
        raise RuntimeError("You need to pass an ObservationMetaData with a rotSkyPos into chipName")

    if not are_arrays:
        ra = np.array([ra])
        dec = np.array([dec])

    xp, yp = _pupilCoordsFromRaDec(ra, dec,
                                   pm_ra=pm_ra, pm_dec=pm_dec,
                                   parallax=parallax, v_rad=v_rad,
                                   obs_metadata=obs_metadata, epoch=epoch)

    ans = chipNameFromPupilCoordsLSST(xp, yp, allow_multiple_chips=allow_multiple_chips)

    if not are_arrays:
        return ans[0]
    return ans


def chipNameFromRaDecLSST(ra, dec, pm_ra=None, pm_dec=None, parallax=None, v_rad=None,
                          obs_metadata=None, epoch=2000.0, allow_multiple_chips=False):
    """
    Return the names of detectors on the LSST camera that see the object specified by
    (RA, Dec) in degrees.

    @param [in] ra in degrees (a numpy array or a float).
    In the International Celestial Reference System.

    @param [in] dec in degrees (a numpy array or a float).
    In the International Celestial Reference System.

    @param [in] pm_ra is proper motion in RA multiplied by cos(Dec) (arcsec/yr)
    Can be a numpy array or a number or None (default=None).

    @param [in] pm_dec is proper motion in dec (arcsec/yr)
    Can be a numpy array or a number or None (default=None).

    @param [in] parallax is parallax in arcsec
    Can be a numpy array or a number or None (default=None).

    @param [in] v_rad is radial velocity (km/s)
    Can be a numpy array or a number or None (default=None).

    @param [in] obs_metadata is an ObservationMetaData characterizing the telescope pointing

    @param [in] epoch is the epoch in Julian years of the equinox against which RA and Dec are
    measured.  Default is 2000.

    @param [in] allow_multiple_chips is a boolean (default False) indicating whether or not
    this method will allow objects to be visible on more than one chip.  If it is 'False'
    and an object appears on more than one chip, only the first chip will appear in the list of
    chipNames but NO WARNING WILL BE EMITTED.  If it is 'True' and an object falls on more than one
    chip, a list of chipNames will appear for that object.

    @param [out] the name(s) of the chips on which ra, dec fall (will be a numpy
    array if more than one)
    """
    if pm_ra is not None:
        pm_ra_out = radiansFromArcsec(pm_ra)
    else:
        pm_ra_out = None

    if pm_dec is not None:
        pm_dec_out = radiansFromArcsec(pm_dec)
    else:
        pm_dec_out = None

    if parallax is not None:
        parallax_out = radiansFromArcsec(parallax)
    else:
        parallax_out = None

    return _chipNameFromRaDecLSST(np.radians(ra), np.radians(dec),
                                  pm_ra=pm_ra_out, pm_dec=pm_dec_out,
                                  parallax=parallax_out, v_rad=v_rad,
                                  obs_metadata=obs_metadata, epoch=epoch,
                                  allow_multiple_chips=allow_multiple_chips)


def _pixelCoordsFromRaDecLSST(ra, dec, pm_ra=None, pm_dec=None, parallax=None, v_rad=None,
                              obs_metadata=None,
                              chipName=None, camera=None,
                              epoch=2000.0, includeDistortion=True):
    """
    Get the pixel positions on the LSST camera (or nan if not on a chip) for objects based
    on their RA, and Dec (in radians)

    @param [in] ra is in radians in the International Celestial Reference System.
    Can be either a float or a numpy array.

    @param [in] dec is in radians in the International Celestial Reference System.
    Can be either a float or a numpy array.

    @param [in] pm_ra is proper motion in RA multiplied by cos(Dec) (radians/yr)
    Can be a numpy array or a number or None (default=None).

    @param [in] pm_dec is proper motion in dec (radians/yr)
    Can be a numpy array or a number or None (default=None).

    @param [in] parallax is parallax in radians
    Can be a numpy array or a number or None (default=None).

    @param [in] v_rad is radial velocity (km/s)
    Can be a numpy array or a number or None (default=None).

    @param [in] obs_metadata is an ObservationMetaData characterizing the telescope
    pointing.

    @param [in] epoch is the epoch in Julian years of the equinox against which
    RA is measured.  Default is 2000.

    @param [in] chipName designates the names of the chips on which the pixel
    coordinates will be reckoned.  Can be either single value, an array, or None.
    If an array, there must be as many chipNames as there are (RA, Dec) pairs.
    If a single value, all of the pixel coordinates will be reckoned on the same
    chip.  If None, this method will calculate which chip each(RA, Dec) pair actually
    falls on, and return pixel coordinates for each (RA, Dec) pair on the appropriate
    chip.  Default is None.

    @param [in] camera is an afwCameraGeom object specifying the attributes of the camera.
    This is an optional argument to be passed to chipName.

    @param [in] includeDistortion is a boolean.  If True (default), then this method will
    return the true pixel coordinates with optical distortion included.  If False, this
    method will return TAN_PIXEL coordinates, which are the pixel coordinates with
    estimated optical distortion removed.  See the documentation in afw.cameraGeom for more
    details.

    @param [out] a 2-D numpy array in which the first row is the x pixel coordinate
    and the second row is the y pixel coordinate
    """

    are_arrays, \
    chipNameList = _validate_inputs_and_chipname([ra, dec], ['ra', 'dec'],
                                                 'pixelCoordsFromRaDecLSST',
                                                 chipName)

    if epoch is None:
        raise RuntimeError("You need to pass an epoch into pixelCoordsFromRaDec")

    if obs_metadata is None:
        raise RuntimeError("You need to pass an ObservationMetaData into pixelCoordsFromRaDec")

    if obs_metadata.mjd is None:
        raise RuntimeError("You need to pass an ObservationMetaData with an mjd into "
                           "pixelCoordsFromRaDec")

    if obs_metadata.rotSkyPos is None:
        raise RuntimeError("You need to pass an ObservationMetaData with a rotSkyPos into "
                           "pixelCoordsFromRaDec")

    xPupil, yPupil = _pupilCoordsFromRaDec(ra, dec,
                                           pm_ra=pm_ra, pm_dec=pm_dec,
                                           parallax=parallax, v_rad=v_rad,
                                           obs_metadata=obs_metadata, epoch=epoch)

    if chipNameList is None:
        chipNameList = chipNameFromPupilCoordsLSST(xPupil, yPupil)

    return pixelCoordsFromPupilCoords(xPupil, yPupil, chipName=chipNameList, camera=lsst_camera(),
                                      includeDistortion=includeDistortion)


def pixelCoordsFromRaDecLSST(ra, dec, pm_ra=None, pm_dec=None, parallax=None, v_rad=None,
                             obs_metadata=None, chipName=None,
                             epoch=2000.0, includeDistortion=True):
    """
    Get the pixel positions on the LSST camera (or nan if not on a chip) for objects based
    on their RA, and Dec (in degrees)

    @param [in] ra is in degrees in the International Celestial Reference System.
    Can be either a float or a numpy array.

    @param [in] dec is in degrees in the International Celestial Reference System.
    Can be either a float or a numpy array.

    @param [in] pm_ra is proper motion in RA multiplied by cos(Dec) (arcsec/yr)
    Can be a numpy array or a number or None (default=None).

    @param [in] pm_dec is proper motion in dec (arcsec/yr)
    Can be a numpy array or a number or None (default=None).

    @param [in] parallax is parallax in arcsec
    Can be a numpy array or a number or None (default=None).

    @param [in] v_rad is radial velocity (km/s)
    Can be a numpy array or a number or None (default=None).

    @param [in] obs_metadata is an ObservationMetaData characterizing the telescope
    pointing.

    @param [in] epoch is the epoch in Julian years of the equinox against which
    RA is measured.  Default is 2000.

    @param [in] chipName designates the names of the chips on which the pixel
    coordinates will be reckoned.  Can be either single value, an array, or None.
    If an array, there must be as many chipNames as there are (RA, Dec) pairs.
    If a single value, all of the pixel coordinates will be reckoned on the same
    chip.  If None, this method will calculate which chip each(RA, Dec) pair actually
    falls on, and return pixel coordinates for each (RA, Dec) pair on the appropriate
    chip.  Default is None.

    @param [in] includeDistortion is a boolean.  If True (default), then this method will
    return the true pixel coordinates with optical distortion included.  If False, this
    method will return TAN_PIXEL coordinates, which are the pixel coordinates with
    estimated optical distortion removed.  See the documentation in afw.cameraGeom for more
    details.

    @param [out] a 2-D numpy array in which the first row is the x pixel coordinate
    and the second row is the y pixel coordinate
    """

    if pm_ra is not None:
        pm_ra_out = radiansFromArcsec(pm_ra)
    else:
        pm_ra_out = None

    if pm_dec is not None:
        pm_dec_out = radiansFromArcsec(pm_dec)
    else:
        pm_dec_out = None

    if parallax is not None:
        parallax_out = radiansFromArcsec(parallax)
    else:
        parallax_out = None

    return _pixelCoordsFromRaDecLSST(np.radians(ra), np.radians(dec),
                                     pm_ra=pm_ra_out, pm_dec=pm_dec_out,
                                     parallax=parallax_out, v_rad=v_rad,
                                     chipName=chipName, obs_metadata=obs_metadata,
                                     epoch=2000.0, includeDistortion=includeDistortion)
