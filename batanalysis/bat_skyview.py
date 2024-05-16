"""
This file holds the BatSkyView object which contains all the necessary sky map information that can be generated from
batfftimage (flux sky image, background variation map, partial coding map).

Tyler Parsotan May 15 2024
"""
import warnings
from pathlib import Path

try:
    import heasoftpy as hsp
except ModuleNotFoundError as err:
    # Error handling
    print(err)


class BatSkyView(object):
    """
    This class holds the information related to a sky image, which is created from a detector plane image

    This is constructed by doing a FFT of the sky image with the detector mask. There can be one or many
    energy or time bins. We can also handle the projection of the image onto a healpix map.

    TODO: create a python FFT deconvolution. This primarily relies on the batfftimage to create the data.
    """

    def __init__(
            self,
            skyimg_file=None,
            dpi_file=None,
            detector_quality_file=None,
            attitude_file=None,
            dpi_data=None,
            input_dict=None,
            recalc=False,
            load_dir=None,
            bkg_dpi_file=None,
            create_bkgvar_map=True,
            create_pcode_map=True
    ):
        """

        :param skyimg_file:
        :param dpi_file:
        :param detector_quality_file:
        :param attitude_file:
        :param dpi_data:
        :param input_dict:
        :param recalc:
        :param load_dir:
        :param bkg_dpi_file:
        """

        if dpi_data is not None:
            raise NotImplementedError(
                "Dealing with the DPI data directly to calculate the sky image is not yet supported.")

        # do some error checking
        if dpi_file is not None:
            self.dpi_file = Path(dpi_file).expanduser().resolve()
            if not self.dpi_file.exists():
                raise ValueError(
                    f"The specified DPI file {self.dpi_file} does not seem "
                    f"to exist. Please double check that it does.")
        else:
            raise ValueError("Please specify a DPI file.")

        # if the user specified a sky image then use it, otherwise set the sky image to be the same name as the dpi
        # and same location
        if skyimg_file is not None:
            self.skyimg_file = Path(skyimg_file).expanduser().resolve()
        else:
            self.skyimg_file = dpi_file.parent.joinpath(f"{dpi_file.stem}.img")

        if detector_quality_file is not None:
            self.detector_quality_file = Path(detector_quality_file).expanduser().resolve()
            if not self.detector_quality_file.exists():
                raise ValueError(
                    f"The specified detector quality mask file {self.detector_quality_file} does not seem "
                    f"to exist. Please double check that it does.")
        else:
            self.detector_quality_file = "NONE"
            warnings.warn("No detector quality mask file has been specified. Sky images will be constructed assuming "
                          "that all detectors are on.", stacklevel=2)

        # make sure that we have an attitude file (technically we dont need it for batfft, but for BatSkyImage object
        # we do)
        if attitude_file is not None:
            self.attitude_file = Path(attitude_file).expanduser().resolve()
            if not self.attitude_file.exists():
                raise ValueError(
                    f"The specified attitude file {self.attitude_file} does not seem "
                    f"to exist. Please double check that it does.")
        else:
            raise ValueError("Please specify an attitude file associated with the DPI.")

    def _call_batfftimage(self, input_dict):
        """
        Calls heasoftpy's batfftimage with an error wrapper, ensures that no runtime errors were encountered

        :param input_dict: Dictionary of inputs that will be passed to heasoftpy's batfftimage
        :return: heasoftpy Result object from batfftimage

        :param input_dict:
        :return:
        """

        input_dict["clobber"] = "YES"
        input_dict["outtype"] = "DPI"

        try:
            return hsp.batfftimage(**input_dict)
        except Exception as e:
            print(e)
            raise RuntimeError(
                f"The call to Heasoft batfftimage failed with inputs {input_dict}."
            )
