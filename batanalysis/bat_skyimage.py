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

# list out the image extensions that we can read in. These should be lowercase.
# note that the snr and background stddev images dont have gti or energy extensions. These are gotten from the
# headers of the images themselves
_file_extension_names = ["image", "pcode", "signif", "varmap"]
_accepted_image_types = ["flux", "pcode", "snr", "stddev", "exposure"]


class BatSkyImage(Histogram):
    """
    This class holds the information related to a sky image, which is created from a detector plane image

    This is constructed by doing a FFT of the sky image with the detector mask. There can be one or many
    energy or time bins. We can also handle the projection of the image onto a healpix map.

    This hold data correspondent to BAT's view of the sky. This can be a flux map (sky image) created from a FFT
    deconvolution, a partial coding map, a significance map, or a background variance map. These can all be energy
    dependent except for the partial coding map.

    TODO: make this class compatible with mosaic-ed data, have it hold the fluxes, etc but also the intermediate
        calculated fluxes etc that allow for quick/easy calculations of mosaic images. Also need to add projection
        to see if when doing projections in energy that we add up the intermediate mosaic images appropriately.
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
            wcs=None,
            is_mosaic_intermediate=False,
            image_type=None
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

        if image_type is not None:
            # make sure it is one of the strings that we recognize internally
            if type(image_type) is not str or not np.any([i == image_type for i in _accepted_image_types]):
                raise TypeError(
                    f"The image_type must be a string that corresponds to one of the following: {_accepted_image_types}")

        if wcs is None:
            warnings.warn(
                "No astropy World Coordinate System has been specified the sky image is assumed to be in the detector "
                "tangent plane. No conversion to Healpix will be possible",
                stacklevel=2,
            )
        else:
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

        # set whether we have a mosaic intermediate image and what type of image we have
        self.is_mosaic_intermediate = is_mosaic_intermediate
        self.image_type = image_type

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
        if isinstance(histogram_data, u.Quantity) or isinstance(histogram_data, Histogram):
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
            # we need to explicitly set the units, so if we have a Quantity object need to do
            # histogram_data.contents.value
            if isinstance(histogram_data.contents, u.Quantity):
                super().__init__(
                    histogram_data.axes,
                    contents=histogram_data.contents.value,
                    labels=histogram_data.axes.labels,
                    unit=hist_unit,
                )
            else:
                super().__init__(
                    histogram_data.axes,
                    contents=histogram_data.contents,
                    labels=histogram_data.axes.labels,
                    unit=hist_unit,
                )
            # for some reason if we try to initialize the parent class when there is a healpix axis in the Histogram that
            # we are using for the intialization, then the self.axes wont have the "HPX" axis as a healpixaxis and we
            # wont be able to access any of the relevant methods for that axis. Therefore try to set the axes explicitly
            if "HPX" in histogram_data.axes.labels:
                self._axes = histogram_data.axes

    def healpix_projection(self, coordsys="galactic", nside=128):
        """
        This creates a healpix projection of the image. The dimension of the array is

        :param coordsys:
        :param nside:
        :return:
        """
        if "HPX" not in self.axes.labels:

            # create our new healpix axis
            hp_ax = HealpixAxis(nside=nside, coordsys=coordsys, label="HPX")

            # create a new array to hold the projection of the sky image in detector tangent plane coordinates to healpix
            # coordinates
            new_array = np.zeros((self.axes['TIME'].nbins, hp_ax.nbins, self.axes["ENERGY"].nbins))

            # for each time/energybin do the projection (ie linear interpolation)
            for t in range(self.axes['TIME'].nbins):
                for e in range(self.axes["ENERGY"].nbins):
                    array, footprint = reproject_to_healpix(
                        (self.slice[t, :, :, e].project("IMY", "IMX").contents, self.wcs), coordsys,
                        nside=nside)
                    new_array[t, :, e] = array

            # create the new histogram
            h = BatSkyImage(Histogram(
                [self.axes['TIME'], hp_ax, self.axes["ENERGY"]],
                contents=new_array, unit=self.unit))

            # can return the histogram or choose to modify the class histogram. If the latter, need to get way to convert back
            # to detector plane coordinates
            # return new_array, footprint, h
        else:
            # need to verify that we have the healpix axis in the correct coordinate system and with correct nsides
            if self.axes["HPX"].nside != nside:
                raise ValueError(
                    "The requested healpix nsides for the BatSkyImage is different from what is contained in the object.")

            if self.axes["HPX"].coordsys.name != coordsys:
                raise ValueError(
                    "The requested healpix coordinate system of the BatSkyImage object is different from what is contained in the object.")

            h = BatSkyImage(image_data=Histogram(self.axes, contents=self.contents, unit=self.unit))

        return h

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

        # for mosaic images, cannot do normal projection with summing up
        if self.is_mosaic_intermediate:
            if tmax_idx - tmin_idx > 1 or emax_idx - emin_idx > 1:
                raise ValueError(
                    f"Cannot do normal addition of a mosaiced image. Please choose a single time/energy bin to plot.")

        # now do the plotting
        if projection is None:
            # use the default spatial axes of the histogram
            # need to determine what this is
            if "IMX" in self.axes.labels:
                ax, mesh = self.slice[tmin_idx:tmax_idx, :, :, emin_idx:emax_idx].project("IMX", "IMY").plot()
                ret = (ax, mesh)
            elif "HPX" in self.axes.labels:
                if "galactic" in coordsys.lower():
                    coord = ["G"]
                elif "icrs" in coordsys.lower():
                    coord = ["G", "C"]
                else:
                    raise ValueError('This plotting function can only plot the healpix map in galactic or icrs '
                                     'coordinates.')
                plot_quantity = self.slice[tmin_idx:tmax_idx, :, emin_idx:emax_idx].project("HPX").contents
                if isinstance(plot_quantity, u.Quantity):
                    plot_quantity = plot_quantity.value

                mesh = projview(plot_quantity,
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
                    self.slice[tmin_idx:tmax_idx, :, :, emin_idx:emax_idx].project("IMY", "IMX").contents.value,
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
                hist = self.healpix_projection(coordsys="galactic", nside=nside)
                if "galactic" in coordsys.lower():
                    coord = ["G"]
                elif "icrs" in coordsys.lower():
                    coord = ["G", "C"]
                else:
                    raise ValueError('This plotting function can only plot the healpix map in galactic or icrs '
                                     'coordinates.')

                plot_quantity = hist.slice[tmin_idx:tmax_idx, :, emin_idx:emax_idx].project("HPX").contents
                if isinstance(plot_quantity, u.Quantity):
                    plot_quantity = plot_quantity.value

                mesh = projview(plot_quantity,
                                coord=coord, graticule=True, graticule_labels=True,
                                projection_type="mollweide", reuse_axes=False)
                ret = (mesh)
            else:
                raise ValueError("The projection value only accepts ra/dec or healpix as inputs.")

        return ret

    @classmethod
    def from_file(cls, file):
        """
        TODO: be able to parse the skyfacet files for mosaicing images
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
                # if "image" in header["EXTNAME"].lower():
                if np.any([name in header["EXTNAME"].lower() for name in _file_extension_names]):
                    img_headers.append(header)
                elif "ebounds" in header["EXTNAME"].lower():
                    energy_header = header
                elif "stdgti" in header["EXTNAME"].lower():
                    time_header = header
                else:
                    raise ValueError(
                        f'An unexpected header extension name {header["EXTNAME"]} was encountered. This class can '
                        f'only parse sky image files that have {_file_extension_names}, EBOUNDS, and STDGTI header extensions. ')

        # now we can construct the data for the time bins, the energy bins, the total sky image array, and the WCS
        w = WCS(img_headers[0])

        # the partial coding image has no units so make sure that only when we are reading in a pcoding or snr file we
        # have this set
        if np.all(["pcode" in i["EXTNAME"].lower() for i in img_headers]) or np.all(
                ["signif" in i["EXTNAME"].lower() for i in img_headers]):
            img_unit = 1 * u.dimensionless_unscaled
        else:
            img_unit = u.Quantity(f'1{img_headers[0]["BUNIT"]}')

        if time_header is not None:
            time_unit = u.Quantity(f'1{time_header["TUNIT1"]}')  # expect seconds
            n_times = time_header["NAXIS2"]
        else:
            time_unit = 1 * u.s
            n_times = 1

        if energy_header is not None:
            energy_unit = u.Quantity(f'1{energy_header["TUNIT2"]}')  # expect keV
            n_energies = energy_header["NAXIS2"]
        else:
            energy_unit = 1 * u.keV
            n_energies = len(img_headers)

        # make sure that we only have 1 time bin (want to enforce this for mosaicing)
        if n_times > 1:
            raise NotImplementedError("The number of timebins for the sky images is greater than 1, which is "
                                      "currently not supported.")

        # maek sure that the number of energy bins is equal to the number of images to read in
        if len(img_headers) != n_energies:
            raise ValueError(
                f'The number of energy bins, {n_energies}, is not equal to the number of images to read in {len(img_headers)}.')

        img_data = np.zeros((n_times, img_headers[0]["NAXIS2"], img_headers[0]["NAXIS1"],
                             n_energies))

        # here we assume that the images are ordered in energy and only have 1 timebin
        energy_data = None
        time_data = None
        with fits.open(input_file) as f:
            for i in range(len(f)):
                data = f[i].data
                header = f[i].header
                # if we have an image, save it to our list of image headers
                # if "image" in header["EXTNAME"].lower():
                if np.any([name in header["EXTNAME"].lower() for name in _file_extension_names]):
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
        if time_data is not None:
            min_t = np.squeeze(time_data["START"] * time_unit.unit)
            max_t = np.squeeze(time_data["STOP"] * time_unit.unit)
        else:
            min_t = img_headers[0]["TSTART"] * time_unit.unit
            max_t = img_headers[0]["TSTOP"] * time_unit.unit

        if energy_data is not None:
            min_e = energy_data["E_MIN"] * energy_unit.unit
            max_e = energy_data["E_MAX"] * energy_unit.unit
        else:
            min_e = [i["E_MIN"] for i in img_headers] * energy_unit.unit
            max_e = [i["E_MAX"] for i in img_headers] * energy_unit.unit

        # define the image type, we have confirmed that is is one of the accepted types, just need to ID which
        # then have to convert the weird file extension to a string that is accepted by the constructor.
        # Note exposure doesnt have an equivalent
        # _file_extension_names = ["image", "pcode", "signif", "varmap"]
        # _accepted_image_types = ["flux", "pcode", "snr", "stddev", "exposure"]

        imtype = [name for name in _file_extension_names if name in img_headers[0]["EXTNAME"].lower()][0]
        if "image" in imtype:
            imtype = "flux"
        elif "signif" in imtype:
            imtype = "snr"
        elif "varmap" in imtype:
            imtype = "stddev"

        return cls(image_data=img_data, tmin=min_t, tmax=max_t, emin=min_e, emax=max_e, wcs=w, image_type=imtype)

    def project(self, *axis):
        """
        This overwrites the parent class project method.
            1) If we have a non-intermediate-mosaic background stddev/snr image, we need to add quantities in quadrature
                instead of just adding the energy bins.
            2) If we have a mosaic intermediate image or a flux image, we can just add directly and calls the Histogram
                project method as normal on the object itself.
            3) If we have an exposure image or a pcode image, then a projection over energy is irrelevant and we just
                want to return a slice of the Histogram (if there is more than 1 energy)
            4) If "ENERGY" is a value specified in axes, then we dont need to worry about any of this
        
        :param axis: 
        :return: 
        """

        # if energy is not specified as a remaining axis OR if there is only 1 energy bin then we dont need to worry
        # about all these nuances. If the image type is not specified, then also go to the normal behavior
        if ("ENERGY" not in [i for i in axis] and self.axes["ENERGY"].nbins > 1) and self.image_type is not None:
            # check to see if we have images that are not intermediate mosaic images and they are stddev/snr quantities
            if not self.is_mosaic_intermediate and np.any([self.image_type == i for i in ["snr", "stddev"]]):
                # because the self.project is recursive below, we need to create a new Histogram object so we call that
                temp_hist = Histogram(edges=self.axes, contents=(self * self).contents.value)
                hist = Histogram(edges=self.axes[*axis], contents=np.sqrt(temp_hist.project(*axis)), unit=self.unit)

            elif np.any([self.image_type == i for i in ["pcode", "exposure"]]):
                # this gets executed even if self.is_mosaic_intermediate is True
                if "HPX" in self.axes.labels:
                    # only have 1 spatial dimension
                    hist = self.slice[:, :, self.end - 1].project(*axis)
                else:
                    # have 2 spatial dimensions
                    hist = self.slice[:, :, :, self.end - 1].project(*axis)
            elif self.is_mosaic_intermediate or self.image_type == "flux":
                hist = super().project(*axis)
            else:
                # capture all other cases with error
                raise ValueError("Cannot do normal sum over energy bins for this type of image.")
        else:
            # warn the user that this image_type isnt set and that we will be using the default behavior to sum
            # over energy
            if self.image_type is None and ("ENERGY" not in [i for i in axis] and self.axes["ENERGY"].nbins > 1):
                warnings.warn(
                    "The image type for this object has not been specified. Defaulting to summing up the Hisotgram values over the ENERGY axis",
                    stacklevel=2,
                )

            hist = super().project(*axis)

        return hist
