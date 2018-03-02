"""
DM-12447 changed the API for afwCameraGeom.  In order to make sure that
we correctly update sims_coordUtils, I am going to generate a catalog
of RA, Dec -> pixel coordinates as transformed using the w.2017.50 version
of afw.  I will then add a unit test to make sure that the same results
come out.  We should expect this test to break if obs_lsstSim ever changes
in a physically meaningful way.  Hopefully, in that case, we will be
expecting it and we can re-run this script to generate a new test catalog.
"""

import numpy as np

from lsst.sims.utils import ObservationMetaData
from lsst.sims.coordUtils import lsst_camera
from lsst.sims.coordUtils import getCornerRaDec
from lsst.sims.coordUtils import focalPlaneCoordsFromRaDec
from lsst.sims.coordUtils import pixelCoordsFromRaDecLSST
from lsst.sims.coordUtils import chipNameFromRaDecLSST

if __name__ == "__main__":

    header_msg = '# This catalog was generated by\n#\n'
    header_msg += '# SIMS_COORDUTILS_DIR/tests/lsstCameraData/make_test_catalog.py\n'
    header_msg += '#\n# It contains data we will use to verify that we have\n'
    header_msg += '# correctly updated sims_coordUtils whenever the API for\n'
    header_msg += '# afwCameraGeom changes.  If obs_lsstSim ever changes in a\n'
    header_msg += '# physically meaningful way, this catalog will need to be\n'
    header_msg += '# regenerated.\n#\n'

    camera = lsst_camera()
    ra = 25.0
    dec = -62.0
    obs = ObservationMetaData(pointingRA=ra, pointingDec=dec,
                              rotSkyPos=57.2, mjd=59586.2)

    ra_range = np.arange(ra-4.0, ra+4.0, 0.1)
    dec_range = np.arange(dec-4.0, dec+4.0, 0.1)

    ra_grid, dec_grid = np.meshgrid(ra_range, dec_range)
    ra_grid = ra_grid.flatten()
    dec_grid = dec_grid.flatten()

    chip_name_grid = chipNameFromRaDecLSST(ra_grid, dec_grid,
                                           obs_metadata=obs)

    valid = np.where(np.char.find(chip_name_grid.astype(str), 'None')<0)

    ra_grid = ra_grid[valid]
    dec_grid = dec_grid[valid]
    chip_name_grid = chip_name_grid[valid]

    focal_x, focal_y = focalPlaneCoordsFromRaDec(ra_grid, dec_grid,
                                                 obs_metadata=obs,
                                                 camera=camera)

    pix_x, pix_y = pixelCoordsFromRaDecLSST(ra_grid, dec_grid,
                                            chipName=chip_name_grid,
                                            obs_metadata=obs)

    with open('lsst_pixel_data.txt', 'w') as out_file:
        out_file.write(header_msg)
        out_file.write('# ra dec chipName focal_x focal_y pix_x pix_y\n')
        for i_obj in range(len(ra_grid)):
            out_file.write('%.2f;%.2f;%s;%.5f;%.5f;%.5f;%.5f\n' %
                           (ra_grid[i_obj], dec_grid[i_obj],
                            chip_name_grid[i_obj],
                            focal_x[i_obj], focal_y[i_obj],
                            pix_x[i_obj], pix_y[i_obj]))

    detector_name_list = [dd.getName() for dd in camera]
    detector_name_list.sort()

    with open('lsst_camera_corners.txt', 'w') as out_file:
        out_file.write(header_msg)
        out_file.write('# chipName ra0 dec0 ra1 dec1 ra2 dec2 ra3 dec3\n')
        for detector_name in detector_name_list:
            corners = getCornerRaDec(detector_name, camera, obs)
            out_file.write('%s;%.4f;%.4f;%.4f;%.4f;%.4f;%.4f;%.4f;%.4f\n' %
            (detector_name, corners[0][0], corners[0][1], corners[1][0],
             corners[1][1], corners[2][0], corners[2][1], corners[3][0],
             corners[3][1]))
