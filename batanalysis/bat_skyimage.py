"""
This file holds the BatSkyImage class which contains binned data from a skymap generated

Tyler Parsotan March 11 2024
"""
import warnings
from copy import deepcopy
from pathlib import Path

import astropy.units as u
import matplotlib as mpl
import matplotlib.axes as maxes
import matplotlib.pyplot as plt
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
from healpy.newvisufunc import projview
from histpy import Histogram, HealpixAxis
from mpl_toolkits.axes_grid1 import make_axes_locatable
from reproject import reproject_to_healpix


class BatSkyImage(Histogram):
    """
    This class holds the information related to a sky image, which is created from a detector plane image

    This is constructed by doing a FFT of the sky image with the detector mask. There can be one or many
    energy or time bins. We can also handle the projection of the image onto a healpix map.

    This hold data correspondent to BAT's view of the sky. This can be a flux map (sky image) created from a FFT
    deconvolution, a partial coding map, a significance map, or a background variance map. These can all be energy
    dependent except for the partial coding map.
    """

    @u.quantity_input(
        timebins=["time"],
        tmin=["time"],
        tmax=["time"],
        energybins=["energy"],
        emin=["energy"],
        emax=["energy"],
    )
    def __init__(
            self,
            image_data=None,
            timebins=None,
            tmin=None,
            tmax=None,
            energybins=None,
            emin=None,
            emax=None,
            weights=None,
            wcs=None
    ):
        """
        This class is meant to hold images of the sky that have been created from a deconvolution of the BAT DPI with
        the coded mask. The sky data can represent flux as a function of energy, background variance as a function of
        energy, the significance map as a function of energy, and the partial coding map.

        This class holds an image for a single time bin for simplicity.

        :param image_data:
        :param timebins:
        :param tmin:
        :param tmax:
        :param energybins:
        :param emin:
        :param emax:
        :param weights:
        """

        # do some error checking
        if image_data is None:
            raise ValueError(
                "A numpy array of a Histpy.Histogram needs to be passed in to initalize a BatSkyImage object"
            )

        if wcs is None:
            warnings.warn(
                "No astropy World Coordinate System has been specified the sky image is assumed to be in the detector "
                "tangent plane. No conversion to Healpix will be possible",
                stacklevel=2,
            )

        if not isinstance(wcs, WCS):
            raise ValueError("The wcs is not an astropy WCS object.")

        parse_data = deepcopy(image_data)

        if (tmin is None and tmax is not None) or (tmax is None and tmin is not None):
            raise ValueError("Both tmin and tmax must be defined.")

        if tmin is not None and tmax is not None:
            if tmin.size != tmax.size:
                raise ValueError("Both tmin and tmax must have the same length.")

        # determine the time binnings
        # can have dfault time binning be the start/end time of the event data or the times passed in by default
        # from a potential histpy Histogram object.
        # also want to make sure that the image is at a single timebin
        if timebins is None and tmin is None and tmax is None:
            if not isinstance(image_data, Histogram):
                # if we dont have a histpy histogram, need to have the timebins
                raise ValueError(
                    "For a general histogram that has been passed in, the timebins need to be specified"
                )
            else:
                timebin_edges = image_data.axes["TIME"].edges
        elif timebins is not None:
            timebin_edges = timebins
        else:
            # use the tmin/tmax
            timebin_edges = u.Quantity([tmin, tmax])

        # make sure that timebin_edges is only 2 elements (meaning 1 time bin)
        if len(timebin_edges) != 2:
            raise ValueError(
                "The BatSkyImage object should be initalized with only 1 timebin. This was initialized with"
                f"{len(timebin_edges) - 1} timebins.")

        # determine the energy binnings
        if energybins is None and emin is None and emax is None:
            if not isinstance(image_data, Histogram):
                # if we dont have a histpy histogram, need to have the energybins
                raise ValueError(
                    "For a general histogram that has been passed in, the energybins need to be specified"
                )
            else:
                energybin_edges = image_data.axes["ENERGY"].edges
        elif energybins is not None:
            energybin_edges = energybins
        else:
            # make sure that emin/emax can be iterated over
            if emin.isscalar:
                emin = u.Quantity([emin])
                emax = u.Quantity([emax])

            # need to determine if the energybins are contiguous
            if np.all(emin[1:] == emax[:-1]):
                # if all the energybins are not continuous combine them directly
                combined_edges = np.concatenate((emin, emax))
                energybin_edges = np.unique(np.sort(combined_edges))

            else:
                # concatenate the emin/emax and sort and then select the unique values. This fill in all the gaps that we
                # may have had. Now we need to modify the input histogram if there was one
                combined_edges = np.concatenate((emin, emax))
                final_energybins = np.unique(np.sort(combined_edges))

                if image_data is not None:
                    idx = np.searchsorted(final_energybins[:-1], emin)

                    # get the new array size
                    new_hist = np.zeros(
                        (
                            *parse_data.shape[:-1],
                            final_energybins.size - 1,
                        )
                    )
                    new_hist[idx, :] = parse_data

                    parse_data = new_hist

                energybin_edges = final_energybins

        # get the good time intervals, the time intervals for the histogram, the energy intervals for the histograms as well
        # these need to be set for us to create the histogram edges
        self.gti = {}
        if tmin is not None:
            self.gti["TIME_START"] = tmin
            self.gti["TIME_STOP"] = tmax
        else:
            self.gti["TIME_START"] = timebin_edges[:-1]
            self.gti["TIME_STOP"] = timebin_edges[1:]
        self.gti["TIME_CENT"] = 0.5 * (self.gti["TIME_START"] + self.gti["TIME_STOP"])

        self.exposure = self.gti["TIME_STOP"] - self.gti["TIME_START"]

        self.tbins = {}
        self.tbins["TIME_START"] = timebin_edges[:-1]
        self.tbins["TIME_STOP"] = timebin_edges[1:]
        self.tbins["TIME_CENT"] = 0.5 * (
                self.tbins["TIME_START"] + self.tbins["TIME_STOP"]
        )

        self.ebins = {}
        if emin is not None:
            self.ebins["INDEX"] = np.arange(emin.size) + 1
            self.ebins["E_MIN"] = emin
            self.ebins["E_MAX"] = emax
        else:
            self.ebins["INDEX"] = np.arange(energybin_edges.size - 1) + 1
            self.ebins["E_MIN"] = energybin_edges[:-1]
            self.ebins["E_MAX"] = energybin_edges[1:]

        self._set_histogram(histogram_data=parse_data, weights=weights)
        self.wcs = wcs

    def _set_histogram(self, histogram_data=None, event_data=None, weights=None):
        """
        This method properly initalizes the Histogram parent class. it uses the self.tbins and self.ebins information
        to define the time and energy binning for the histogram that is initalized.

        COPIED from DetectorPlaneHist class, can be organized better.

        :param histogram_data: None or histpy Histogram or a numpy array of N dimensions. Thsi should be formatted
            such that it has the following dimensions: (T,Ny,Nx,E) where T is the number of timebins, Ny is the
            number of image pixels in the y direction, Nx represents an identical
            quantity in the x direction, and E is the number of energy bins. These should be the appropriate sizes for
            the tbins and ebins attributes
        :param event_data: None or Event data dictionary or event data class (to be created)
        :param weights: None or the weights of the same size as event_data or histogram_data
        :return: None
        """

        # get the timebin edges
        timebin_edges = (
                np.zeros(self.tbins["TIME_START"].size + 1) * self.tbins["TIME_START"].unit
        )
        timebin_edges[:-1] = self.tbins["TIME_START"]
        timebin_edges[-1] = self.tbins["TIME_STOP"][-1]

        # get the energybin edges
        energybin_edges = (
                np.zeros(self.ebins["E_MIN"].size + 1) * self.ebins["E_MIN"].unit
        )
        energybin_edges[:-1] = self.ebins["E_MIN"]
        energybin_edges[-1] = self.ebins["E_MAX"][-1]

        # create our histogrammed data
        if isinstance(histogram_data, u.Quantity):
            hist_unit = histogram_data.unit
        else:
            hist_unit = u.count

        if not isinstance(histogram_data, Histogram):
            # need to make sure that the histogram_data has the correct shape ie be 4 dimensional arranged as (T,Ny,Nx,E)
            if np.ndim(histogram_data) != 4:
                raise ValueError(f'The size of the input sky image is a {np.ndim(histogram_data)} dimensional array'
                                 f'which needs to be a 4D array arranged as (T,Ny,Nx,E) where T is the number of '
                                 f'timebins, Ny is the number of image y pixels, Nx is the number of image x pixels,'
                                 f' and E is the number of energy bins.')

            # see if the shape of the image data is what it should be
            if np.shape(histogram_data) != (
                    self.tbins["TIME_START"].size,
                    histogram_data.shape[1], histogram_data.shape[2],
                    self.ebins["E_MIN"].size,
            ):
                raise ValueError(f'The shape of the input sky image is {np.shape(histogram_data)} while it should be'
                                 f'{(self.tbins["TIME_START"].size, histogram_data.shape[1], histogram_data.shape[2], self.ebins["E_MIN"].size)}')
            super().__init__(
                [
                    timebin_edges,
                    np.arange(histogram_data.shape[1] + 1) - 0.5,
                    np.arange(histogram_data.shape[2] + 1) - 0.5,
                    energybin_edges,
                ],
                contents=histogram_data,
                labels=["TIME", "IMY", "IMX", "ENERGY"],
                sumw2=weights,
                unit=hist_unit,
            )
        else:
            super().__init__(
                [i.edges for i in histogram_data.axes],
                contents=histogram_data.contents,
                labels=histogram_data.axes.labels,
                unit=hist_unit,
            )

    def healpix_projection(self, coordsys="galactic", nside=128):
        """
        This creates a healpix projection of the image. The dimension of the array is

        :param coordsys:
        :param nside:
        :return:
        """

        # create our new healpix axis
        hp_ax = HealpixAxis(nside=nside, coordsys=coordsys, label="HPX")

        # create a new array to hold the projection of the sky image in detector tangent plane coordinates to healpix
        # coordinates
        new_array = np.zeros((self.axes['TIME'].nbins, hp_ax.nbins, self.axes["ENERGY"].nbins))

        # for each time/energybin do the projection (ie linear interpolation)
        for t in range(self.axes['TIME'].nbins):
            for e in range(self.axes["ENERGY"].nbins):
                array, footprint = reproject_to_healpix((self.project("IMY", "IMX").contents, self.wcs), coordsys,
                                                        nside=nside)
                new_array[t, :, e] = array

        # create the new histogram
        h = Histogram(
            [self.axes['TIME'], hp_ax, self.axes["ENERGY"]],
            contents=new_array)

        # can return the histogram or choose to modify the class histogram. If the latter, need to get way to convert back
        # to detector plane coordinates
        return new_array, footprint, h

    def calc_radec(self):
        """

        :return:
        """
        from .mosaic import convert_xy2radec

        x = np.arange(self.axes["IMX"].nbins)
        y = np.arange(self.axes["IMY"].nbins)
        xx, yy = np.meshgrid(x, y)

        ra, dec = convert_xy2radec(xx, yy, self.wcs)

        c = SkyCoord(ra=ra, dec=dec, frame="icrs", unit="deg")

        return c.ra, c.dec

    def calc_glatlon(self):
        """

        :return:
        """

        ra, dec = self.calc_radec()

        c = SkyCoord(ra=ra, dec=dec, frame="icrs", unit="deg")

        return c.galactic.l, c.galactic.b

    @u.quantity_input(emin=["energy"], emax=["energy"], tmin=["time"], tmax=["time"])
    def plot(self, emin=None, emax=None, tmin=None, tmax=None, projection=None, coordsys="galactic", nside=128):
        """
        This is a convenience plotting function that allows for quick and easy plotting of a sky image. It allows for
        energy and time (where applicable) slices and different representations of the sky image.

        :param emin:
        :param emax:
        :param tmin:
        :param tmax:
        :param projection:
        :param coordsys:
        :param nside:
        :return:
        """

        # do some error checking
        if emin is None and emax is None:
            emin = self.axes["ENERGY"].lo_lim
            emax = self.axes["ENERGY"].hi_lim
        elif emin is not None and emax is not None:
            if emin not in self.axes["ENERGY"].edges or emax not in self.axes["ENERGY"].edges:
                raise ValueError(
                    f'The passed in emin or emax value is not a valid ENERGY bin edge: {self.axes["ENERGY"].edges}')
        else:
            raise ValueError("emin and emax must either both be None or both be specified.")

        if tmin is None and tmax is None:
            tmin = self.axes["TIME"].lo_lim
            tmax = self.axes["TIME"].hi_lim
        elif tmin is not None and tmax is not None:
            if tmin not in self.axes["TIME"].edges or tmax not in self.axes["TIME"].edges:
                raise ValueError(
                    f'The passed in tmin or tmax value is not a valid TIME bin edge: {self.axes["TIME"].edges}')
        else:
            raise ValueError("tmin and tmax must either both be None or both be specified.")

        # get the bin index to then do slicing and projecting for plotting. Need to make sure that the inputs are
        # single numbers (not single element array) which is why we do __.item()
        tmin_idx = self.axes["TIME"].find_bin(tmin.item())
        tmax_idx = self.axes["TIME"].find_bin(tmax.item())

        emin_idx = self.axes["ENERGY"].find_bin(emin.item())
        emax_idx = self.axes["ENERGY"].find_bin(emax.item())

        # now do the plotting
        if projection is None:
            # use the default spatial axes of the histogram
            # need to determine what this is
            if "IMX" in self.axes.labels:
                ax, mesh = self.slice[tmin_idx:tmax_idx + 1, :, :, emin_idx:emax_idx + 1].project("IMX", "IMY").plot()
                ret = (ax, mesh)
            elif "HPX" in self.axes.labels:
                if "galactic" in coordsys.lower():
                    coord = ["G"]
                elif "icrs" in coordsys.lower():
                    coord = ["G", "C"]
                else:
                    raise ValueError('This plotting function can only plot the healpix map in galactic or icrs '
                                     'coordinates.')
                mesh = projview(self.slice[tmin_idx:tmax_idx + 1, :, emin_idx:emax_idx + 1].project("HPX").contents,
                                coord=coord, graticule=True, graticule_labels=True,
                                projection_type="mollweide", reuse_axes=False)
                ret = (mesh)
            else:
                raise ValueError("The spatial projection of the sky image is currently not accepted as a plotting "
                                 "option. Please convert to IMX/IMY or a HEALPix map.")
        else:
            # the user has specified different options, can be ra/dec or healpix (with coordsys of galactic or icrs)
            # if we want Ra/Dec
            if "ra/dec" in projection.lower():
                fig = plt.figure()
                ax = fig.add_subplot(1, 1, 1, projection=self.wcs)
                divider = make_axes_locatable(ax)
                cax = divider.append_axes("right", size="5%", pad=0.05, axes_class=maxes.Axes)
                cmap = mpl.colormaps.get_cmap("viridis")
                cmap.set_bad(color="w")

                ax.grid(color='k', ls='solid')
                im = ax.imshow(
                    self.slice[tmin_idx:tmax_idx + 1, :, :, emin_idx:emax_idx + 1].project("IMY", "IMX").contents.value,
                    origin="lower")
                cbar = fig.colorbar(im, cax=cax, orientation="vertical", label=self.unit, ticklocation="right",
                                    location="right")
                ax.coords["ra"].set_axislabel("RA")
                ax.coords["dec"].set_axislabel("Dec")
                ax.coords["ra"].set_major_formatter("d.ddd")
                ax.coords["dec"].set_major_formatter("d.ddd")

                # to overplot here need to do eg. ax.plot(244.979,-15.6400,'bs', transform=ax.get_transform('world'))

                ret = (fig, ax)
            elif "healpix" in projection.lower():
                new_array, footprint, hist = self.healpix_projection(coordsys="galactic", nside=nside)
                if "galactic" in coordsys.lower():
                    coord = ["G"]
                elif "icrs" in coordsys.lower():
                    coord = ["G", "C"]
                else:
                    raise ValueError('This plotting function can only plot the healpix map in galactic or icrs '
                                     'coordinates.')
                mesh = projview(hist.slice[tmin_idx:tmax_idx + 1, :, emin_idx:emax_idx + 1].project("HPX").contents,
                                coord=coord, graticule=True, graticule_labels=True,
                                projection_type="mollweide", reuse_axes=False)
                ret = (mesh)
            else:
                raise ValueError("The projection value only accepts ra/dec or healpix as inputs.")

        return ret

    @classmethod
    def from_file(cls, file):
        """
        TODO: be able to parse files with images, background variance, SNR map, and partial coding file all in the same file
        :param file:
        :return:
        """

        input_file = Path(file).expanduser().resolve()
        if not input_file.exists():
            raise ValueError(f"The specified sky image file {input_file} does not seem to exist. "
                             f"Please double check that it does.")

        # read the file header
        img_headers = []
        energy_header = None
        time_header = None
        with fits.open(input_file) as f:
            for i in range(len(f)):
                header = f[i].header
                # if we have an image, save it to our list of image headers
                if "image" in header["EXTNAME"].lower():
                    img_headers.append(header)
                elif "ebounds" in header["EXTNAME"].lower():
                    energy_header = header
                elif "stdgti" in header["EXTNAME"].lower():
                    time_header = header
                else:
                    raise ValueError(
                        f'An unexpected header extension name {header["EXTNAME"]} was encountered. This class can '
                        f'only parse sky image files that have IMAGE, EBOUNDS, and STDGTI header extensions. ')

        # now we can construct the data for the time bins, the energy bins, the total sky image array, and the WCS
        w = WCS(img_headers[0])
        img_unit = u.Quantity(f'1{img_headers[0]["BUNIT"]}')
        time_unit = u.Quantity(f'1{time_header["TUNIT1"]}')  # expect seconds
        energy_unit = u.Quantity(f'1{energy_header["TUNIT2"]}')  # expect keV

        # make sure that we only have 1 time bin (want to enforce this for mosaicing)
        if time_header["NAXIS2"] > 1:
            raise NotImplementedError("The number of timebins for the sky images is greater than 1, which is "
                                      "currently not supported.")

        # maek sure that the number of energy bins is equal to the number of images to read in
        if len(img_headers) != energy_header["NAXIS2"]:
            raise ValueError(
                f'The number of energy bins, {energy_header["NAXIS2"]}, is not equal to the number of images to read in {len(img_headers)}.')

        img_data = np.zeros((time_header["NAXIS2"], img_headers[0]["NAXIS2"], img_headers[0]["NAXIS1"],
                             energy_header["NAXIS2"]))

        # here we assume that the images are ordered in energy and only have 1 timebin
        with fits.open(input_file) as f:
            for i in range(len(f)):
                data = f[i].data
                header = f[i].header
                # if we have an image, save it to our list of image headers
                if "image" in header["EXTNAME"].lower():
                    img_data[:, :, :, i] = data
                elif "ebounds" in header["EXTNAME"].lower():
                    energy_data = data
                elif "stdgti" in header["EXTNAME"].lower():
                    time_data = data
                else:
                    raise ValueError(
                        f'An unexpected header extension name {header["EXTNAME"]} was encountered. This class can '
                        f'only parse sky image files that have IMAGE, EBOUNDS, and STDGTI header extensions. ')

        # set the unit for the sky image
        img_data *= img_unit.unit

        # parse the time/energy to initalize our BatSkyImage
        min_t = time_data["START"] * time_unit.unit
        max_t = time_data["STOP"] * time_unit.unit
        min_e = energy_data["E_MIN"] * energy_unit.unit
        max_e = energy_data["E_MAX"] * energy_unit.unit

        return cls(image_data=img_data, tmin=min_t, tmax=max_t, emin=min_e, emax=max_e, wcs=w)