import os
import numpy as np
from astropy.io import fits
import scipy.constants as sc
from .annulus import annulus

__all__ = ['imagecube']


class imagecube(object):
    """
    Base class containing all the FITS data. Must be a 3D cube containing two
    spatial and one velocity axis for and spectral shifting. A 2D 'cube' can
    be used to make the most of the deprojection routines. These can easily be
    made from CASA using the ``exportfits()`` command.

    Args:
        path (str): Relative path to the FITS cube.
        FOV (Optional[float]): Clip the image cube down to a specific
            field-of-view spanning a range ``FOV``, where ``FOV`` is in
            [arcsec].
        v_range (Optional[tuple]): A tuple of minimum and maximum velocities
            to clip the velocity range to.
        verbose (Optional[bool]): Whether to print out warning messages.
        primary_beam (Optional[str]): Path to the primary beam as a FITS file
            to apply the correction.
    """

    frequency_units = {'GHz': 1e9, 'MHz': 1e6, 'kHz': 1e3, 'Hz': 1e0}
    velocity_units = {'km/s': 1e3, 'm/s': 1e0}

    def __init__(self, path, FOV=None, velocity_range=None, verbose=True,
                 clip=None, primary_beam=None):
        self._read_FITS(path)
        self.verbose = verbose

        # Primary beam correction.
        self._pb_corrected = False
        if primary_beam is not None:
            self.correct_PB(primary_beam)

        if clip is not None:
            print("WARNING: `clip` is depreciated, use `FOV` instead.")
            FOV = clip

        if FOV is not None:
            self._clip_cube_spatial(FOV/2.0)
        if velocity_range is not None:
            self._clip_cube_velocity(*velocity_range)
        if self.data.ndim != 3 and self.verbose:
            print("WARNING: Provided cube is only 2D. Shifting not available.")

    # -- Fishing Functions -- #

    def average_spectrum(self, r_min=None, r_max=None, dr=None,
                         PA_min=None, PA_max=None, exclude_PA=False,
                         abs_PA=False, x0=0.0, y0=0.0, inc=0.0, PA=0.0, z0=0.0,
                         psi=1.0, z1=0.0, phi=1.0, z_func=None, mstar=1.0,
                         dist=100., resample=1, beam_spacing=False,
                         mask_frame='disk', unit='Jy/beam', mask=None,
                         assume_correlated=True, skip_empty_annuli=True,
                         shadowed=True):
        """
        Return the averaged spectrum over a given radial range, returning a
        spectrum in units of [Jy/beam] or [K] using the Rayleigh-Jeans
        approximation.

        The `resample` parameter allows you to resample the
        spectrum at a different velocity spacing (by providing a float
        argument) or averaging of an integer number of channels (by providing
        an integer argument). For example, ``resample=3``, will return a
        velocity axis which has been supersampled such that a channel is three
        times as narrow as the intrinsic width. Instead, ``resample=50.0`` will
        result in a velocity axis with a channel spacing of 50 m/s.

        .. note::

            The third variable returned is the scatter in each velocity bin and
            not the uncertainty on the bin mean as the data is not strictly
            independent due to spectral and spatial correlations in the data.
            If you want to assume uncorrelated data to get a better estimate of
            the uncertainty, set ``assumed_correlated=False``.

        Args:
            r_min (Optional[float]): Inner radius in [arcsec] of the region to
                integrate.
            r_max (Optional[float]): Outer radius in [arcsec] of the region to
                integrate.
            dr (Optional[float]): Width of the annuli to split the integrated
                region into in [arcsec]. Default is quater of the beam major
                axis.
            PA_min (Optional[float]): Minimum polar angle of the segment of the
                annulus in [degrees]. Note this is the polar angle, not the
                position angle.
            PA_max (Optional[float]): Maximum polar angle of the segment of the
                annulus in [degrees]. Note this is the polar angle, not the
                position angle.
            exclude_PA (Optional[bool]): If ``True``, exclude the provided
                polar angle range rather than include it.
            abs_PA (Optional[bool]): If ``True``, take the absolute value of
                the polar angle such that it runs from 0 [deg] to 180 [deg].
            x0 (Optional[float]): Source center offset along the x-axis in
                [arcsec].
            y0 (Optional[float]): Source center offset along the y-axis in
                [arcsec].
            inc (Optional[float]): Inclination of the disk in [degrees].
            PA (Optional[float]): Position angle of the disk in [degrees],
                measured east-of-north towards the redshifted major axis.
            z0 (Optional[float]): Emission height in [arcsec] at a radius of
                1".
            psi (Optional[float]): Flaring angle of the emission surface.
            z1 (Optional[float]): Correction to emission height at 1" in
                [arcsec].
            phi (Optional[float]): Flaring angle correction term.
            z_func (Optional[function]): A function which provides
                :math:`z(r)`. Note that no checking will occur to make sure
                this is a valid function.
            mstar (Optional[float]): Stellar mass in [Msun].
            dist (Optional[float]): Distance to the source in [pc].
            resample (Optional[float/int]): Resampling parameter for the
                deprojected spectrum. An integer specifies an average of that
                many channels, while a float specifies the desired channel
                width. Default is ``resample=1``.
            beam_spacing(Optional[bool]): When extracting the annuli, whether
                to choose spatially independent pixels or not.
            PA_min (Optional[float]): Minimum polar angle to include in the
                annulus in [degrees]. Note that the polar angle is measured in
                the disk-frame, unlike the position angle which is measured in
                the sky-plane.
            PA_max (Optional[float]): Maximum polar angleto include in the
                annulus in [degrees]. Note that the polar angle is measured in
                the disk-frame, unlike the position angle which is measured in
                the sky-plane.
            exclude_PA (Optional[bool]): Whether to exclude pixels where
                ``PA_min <= PA_pix <= PA_max``.
            mask_frame (Optional[str]): Which frame the radial and azimuthal
                mask is specified in, either ``'disk'`` or ``'sky'``.
            unit (Optional[str]): Units for the spectrum, either ``'Jy/beam'``
                or ``'K'``. Note that the conversion to Kelvin assumes the
                Rayleigh-Jeans approximation which is typically invalid at
                sub-mm wavelengths.
            assume_correlated (Optional[bool]): Whether to treat the spectra
                which are stacked as correlated, by default this is
                ``True``. If ``False``, the uncertainty will be estimated using
                Poisson statistics, otherwise the uncertainty is just the
                standard deviation of each velocity bin.
            skip_empty_annuli (Optional[bool]): If ``True``, skip any annuli
                which are empty (i.e. their masks have zero pixels in). If
                ``False``, any empty masks will raise a ``ValueError``.

        Returns:
            The velocity axis of the spectrum, ``velax``, in [m/s], the
            averaged spectrum, ``spectrum``, and the variance of the velocity
            bin, ``scatter``. The latter two are in units of either [Jy/beam]
            or [K] depending on the ``unit``.
        """
        # Check is cube is 2D.
        self._test_2D()

        # Get the integration ranges.
        if r_min is None and r_max is None:
            rbins, rvals = self.radial_sampling(rbins=None, rvals=None, dr=dr)
            r_min, r_max = rbins[0], rbins[-1]

        # Figure out the radial binning.
        if dr is None:
            dr = 2. * self.dpix if self.dpix == self.bmaj else self.bmaj / 4.
        nbins = max(1, int(np.floor((r_max - r_min) / dr)))
        rbins = np.linspace(r_min, r_max, nbins + 1)
        _, rvals = self.radial_sampling(rbins=rbins)

        # Keplerian velocity at the annulus centers.
        v_kep = self._keplerian(rpnts=rvals, mstar=mstar, dist=dist, inc=inc,
                                z0=z0, psi=psi, z1=z1, phi=phi, z_func=z_func)
        v_kep = np.atleast_1d(v_kep)

        # Output unit.
        unit = unit.lower()
        if unit not in ['mjy/beam', 'jy/beam', 'mk', 'k']:
            raise ValueError("Unknown `unit`.")
        if resample < 1.0 and self.verbose:
            print('WARNING: `resample < 1`, are you sure you want channels '
                  + 'more narrow than 1 m/s?')

        # Pseduo masking. Make everything masked a NaN and then revert.
        if mask is not None:
            saved_data = self.data.copy()
            self.data = np.where(mask, self.data, np.nan)

        # Get the deprojected spectrum for each annulus.
        # Have an array to describe whether an annulus is included in the
        # average or not.
        spectra, scatter, included = [], [], np.ones(rvals.size).astype('int')
        for ridx in range(rvals.size):
            try:
                annulus = self.get_annulus(rbins[ridx], rbins[ridx+1],
                                           x0=x0, y0=y0, inc=inc, PA=PA, z0=z0,
                                           psi=psi, z1=z1, phi=phi,
                                           beam_spacing=beam_spacing,
                                           PA_min=PA_min, PA_max=PA_max,
                                           exclude_PA=exclude_PA,
                                           abs_PA=abs_PA,
                                           mask_frame=mask_frame,
                                           shadowed=shadowed)
                x, y, dy = annulus.deprojected_spectrum(vrot=v_kep[ridx],
                                                        resample=resample,
                                                        scatter=True)
                spectra += [y]
                scatter += [dy]
            except ValueError:
                msg = "No pixels in the mask between "
                msg += "{:.2f} ".format(rbins[ridx])
                msg += "and {:.2f} arcsec.".format(rbins[ridx+1])
                if not skip_empty_annuli:
                    raise ValueError(msg)
                else:
                    included[ridx] = 0
                    if self.verbose:
                        print("WARNING: " + msg + " Skipping annulus.")

        # Return the data.
        if mask is not None:
            self.data = saved_data

        # Remove any pesky NaNs.
        spectra = np.where(np.isfinite(spectra), spectra, 0.0)
        scatter = np.where(np.isfinite(scatter), scatter, 0.0)

        # Weight the annulus based on its area.
        weights = np.pi * (rbins[1:]**2 - rbins[:-1]**2)
        weights = weights[included.astype('bool')]
        weights += 1e-20 * np.random.randn(weights.size)
        if weights.size != spectra.shape[0]:
            raise ValueError("Number of weights, {:d}, ".format(weights.size)
                             + "does not match number of spectra, "
                             + "{:d}.".format(spectra.shape[0]))
        spectrum = np.average(spectra, axis=0, weights=weights)

        # Uncertainty propagation.
        scatter = np.average(scatter, axis=0, weights=weights)
        if not assume_correlated:
            N = annulus.theta.size * np.diff(x).mean() / self.chan
            if not beam_spacing:
                N *= self.dpix**2 / self._calculate_beam_area_arcsec()
            scatter /= np.sqrt(N)

        # Convert to K using RJ-approximation.
        if unit == 'k':
            spectrum = self.jybeam_to_Tb_RJ(spectrum)
            scatter = self.jybeam_to_Tb_RJ(scatter)
        if unit[0] == 'm':
            spectrum *= 1e3
            scatter *= 1e3
        return x, spectrum, scatter

    def integrated_spectrum(self, r_min=None, r_max=None, dr=None, x0=0.0,
                            y0=0.0, inc=0.0, PA=0.0, z0=0.0, psi=1.0, z1=0.0,
                            phi=1.0, z_func=None, mstar=1.0, dist=100.,
                            resample=1, beam_spacing=False, PA_min=None,
                            PA_max=None, exclude_PA=False, abs_PA=False,
                            mask=None, mask_frame='disk',
                            assume_correlated=False, skip_empty_annuli=True,
                            shadowed=True):
        """
        Return the integrated spectrum over a given radial range, returning a
        spectrum in units of [Jy].

        The `resample` parameter allows you to resample the
        spectrum at a different velocity spacing (by providing a float
        argument) or averaging of an integer number of channels (by providing
        an integer argument). For example, ``resample=3``, will return a
        velocity axis which has been supersampled such that a channel is three
        times as narrow as the intrinsic width. Instead, ``resample=50.0`` will
        result in a velocity axis with a channel spacing of 50 m/s.

        .. note::

            The third variable returned is the scatter in each velocity bin and
            not the uncertainty on the bin mean as the data is not strictly
            independent due to spectral and spatial correlations in the data.
            If you want to assume uncorrelated data to get a better estimate of
            the uncertainty, set ``assumed_correlated=False``.

        Args:
            r_min (Optional[float]): Inner radius in [arcsec] of the region to
                integrate.
            r_max (Optional[float]): Outer radius in [arcsec] of the region to
                integrate.
            dr (Optional[float]): Width of the annuli to split the
                integrated region into in [arcsec]. Default is quater of the
                beam major axis.
            x0 (Optional[float]): Source center offset along the x-axis in
                [arcsec].
            y0 (Optional[float]): Source center offset along the y-axis in
                [arcsec].
            inc (Optional[float]): Inclination of the disk in [degrees].
            PA (Optional[float]): Position angle of the disk in [degrees],
                measured east-of-north towards the redshifted major axis.
            z0 (Optional[float]): Emission height in [arcsec] at a radius of
                1".
            psi (Optional[float]): Flaring angle of the emission surface.
            z1 (Optional[float]): Correction to emission height at 1" in
                [arcsec].
            phi (Optional[float]): Flaring angle correction term.
            z_func (Optional[function]): A function which provides
                :math:`z(r)`. Note that no checking will occur to make sure
                this is a valid function.
            mstar (Optional[float]): Stellar mass in [Msun].
            dist (Optional[float]): Distance to the source in [pc].
            resample(Optional[float/int]): Resampling parameter for the
                deprojected spectrum. An integer specifies an average of that
                many channels, while a float specifies the desired channel
                width. Default is ``resample=1``.
            beam_spacing(Optional[bool]): When extracting the annuli, whether
                to choose spatially independent pixels or not.
            PA_min (Optional[float]): Minimum polar angle to include in the
                annulus in [degrees]. Note that the polar angle is measured in
                the disk-frame, unlike the position angle which is measured in
                the sky-plane.
            PA_max (Optional[float]): Maximum polar angleto include in the
                annulus in [degrees]. Note that the polar angle is measured in
                the disk-frame, unlike the position angle which is measured in
                the sky-plane.
            exclude_PA (Optional[bool]): Whether to exclude pixels where
                ``PA_min <= PA_pix <= PA_max``.
            abs_PA (Optional[bool]): If ``True``, take the absolute value of
                the polar angle such that it runs from 0 [deg] to 180 [deg].
            mask_frame (Optional[str]): Which frame the radial and azimuthal
                mask is specified in, either ``'disk'`` or ``'sky'``.
            assume_correlated (Optional[bool]): Whether to treat the spectra
                which are stacked as correlated, by default this is
                ``True``. If ``False``, the uncertainty will be estimated using
                Poisson statistics, otherwise the uncertainty is just the
                standard deviation of each velocity bin.
            skip_empty_annuli (Optional[bool]): If ``True``, skip any annuli
                which are empty (i.e. their masks have zero pixels in). If
                ``False``, any empty masks will raise a ``ValueError``.

        Returns:
            The velocity axis of the spectrum, ``velax``, in [m/s], the
            integrated spectrum, ``spectrum``, and the variance of the velocity
            bin, ``scatter``. The latter two are in units of [Jy].

        """
        # Check is cube is 2D.
        self._test_2D()

        # Get average spectrum.
        x, y, dy = self.average_spectrum(r_min=r_min, r_max=r_max, dr=dr,
                                         x0=x0, y0=y0, inc=inc, PA=PA, z0=z0,
                                         psi=psi, z1=z1, phi=phi,
                                         z_func=z_func, mstar=mstar, dist=dist,
                                         resample=resample,
                                         beam_spacing=beam_spacing,
                                         PA_min=PA_min, PA_max=PA_max,
                                         exclude_PA=exclude_PA, abs_PA=abs_PA,
                                         mask=mask, mask_frame=mask_frame,
                                         assume_correlated=assume_correlated,
                                         skip_empty_annuli=skip_empty_annuli,
                                         shadowed=shadowed)

        # Calculate the area of the mask.
        if mask is None:
            mask = self.get_mask(r_min=r_min, r_max=r_max, PA_min=PA_min,
                                 PA_max=PA_max, exclude_PA=exclude_PA,
                                 abs_PA=abs_PA, mask_frame=mask_frame, x0=x0,
                                 y0=y0, inc=inc, PA=PA, z0=z0, psi=psi, z1=z1,
                                 phi=phi, z_func=z_func, shadowed=shadowed)
        nb = np.sum(mask) * self.dpix**2 / self._calculate_beam_area_arcsec()

        # Return
        return x, y * nb, dy * nb

    def radial_spectra(self, rvals=None, rbins=None, dr=None, x0=0.0,
                       y0=0.0, inc=0.0, PA=0.0, z0=0.0, psi=1.0, z1=0.0,
                       phi=1.0, z_func=None, mstar=1.0, dist=100., resample=1,
                       beam_spacing=False, r_min=None, r_max=None,
                       PA_min=None, PA_max=None, exclude_PA=None, abs_PA=False,
                       mask_frame='disk', mask=None, assume_correlated=True,
                       unit='Jy/beam', shadowed=True):
        """
        Return shifted and stacked spectra, either integrated flux or average
        spectrum, along the provided radial profile. Possible units for the
        flux (density) are:

            - ``'mJy/beam'``
            - ``'Jy/beam'``
            - ``'mK'``
            - ``'K'``
            - ``'mJy'``
            - ``'Jy'``

        Args:
            rvals (Optional[floats]): Array of bin centres for the profile in
                [arcsec]. You need only specify one of ``rvals`` and ``rbins``.
            rbins (Optional[floats]): Array of bin edges for the profile in
                [arcsec]. You need only specify one of ``rvals`` and ``rbins``.
            dr (Optional[float]): Width of the radial bins in [arcsec] to
                use if neither ``rvals`` nor ``rbins`` is set. Default is 1/4
                of the beam major axis.
            x0 (Optional[float]): Source center offset along the x-axis in
                [arcsec].
            y0 (Optional[float]): Source center offset along the y-axis in
                [arcsec].
            inc (Optional[float]): Inclination of the disk in [degrees].
            PA (Optional[float]): Position angle of the disk in [degrees],
                measured east-of-north towards the redshifted major axis.
            z0 (Optional[float]): Emission height in [arcsec] at a radius of
                1".
            psi (Optional[float]): Flaring angle of the emission surface.
            z1 (Optional[float]): Correction to emission height at 1" in
                [arcsec].
            phi (Optional[float]): Flaring angle correction term.
            z_func (Optional[function]): A function which provides
                :math:`z(r)`. Note that no checking will occur to make sure
                this is a valid function.
            mstar (Optional[float]): Stellar mass in [Msun].
            dist (Optional[float]): Distance to the source in [pc].
            resample(Optional[float/int]): Resampling parameter for the
                deprojected spectrum. An integer specifies an average of that
                many channels, while a float specifies the desired channel
                width. Default is ``resample=1``.
            beam_spacing(Optional[bool]): When extracting the annuli, whether
                to choose spatially independent pixels or not.
            r_min (Optional[float]): Inner radius in [arcsec] of the region to
                integrate. The value used will be greater than or equal to
                ``r_min``.
            r_max (Optional[float]): Outer radius in [arcsec] of the region to
                integrate. The value used will be less than or equal to
                ``r_max``.
            PA_min (Optional[float]): Minimum polar angle to include in the
                annulus in [degrees]. Note that the polar angle is measured in
                the disk-frame, unlike the position angle which is measured in
                the sky-plane.
            PA_max (Optional[float]): Maximum polar angleto include in the
                annulus in [degrees]. Note that the polar angle is measured in
                the disk-frame, unlike the position angle which is measured in
                the sky-plane.
            exclude_PA (Optional[bool]): Whether to exclude pixels where
                ``PA_min <= PA_pix <= PA_max``. Default is ``False``.
            abs_PA (Optional[bool]): If ``True``, take the absolute value of
                the polar angle such that it runs from 0 [deg] to 180 [deg].
            mask_frame (Optional[str]): Which frame the radial and azimuthal
                mask is specified in, either ``'disk'`` or ``'sky'``.
            assume_correlated (Optional[bool]): Whether to treat the spectra
                which are stacked as correlated, by default this is
                ``True``. If ``False``, the uncertainty will be estimated using
                Poisson statistics, otherwise the uncertainty is just the
                standard deviation of each velocity bin.
            unit (Optional[str]): Desired unit of the output spectrum.

        Returns:
            An array of the bin centers, ``rvals``, and an array of deprojected
            spectra. This will have shape (M, 3, N) where M is the number of
            radial samples, ``rvals.size`` and N is the number of channels,
            ``velax.size`` if ``resample=1``. The three arrays are the velocity
            axis in [m/s], the spectrum, in either [Jy] or [Jy/beam] depending
            on the choice of ``spectrum``, and the uncertainty in the same
            units.
        """

        # Check is cube is 2D.
        self._test_2D()

        # Radial sampling with radial boundaries.
        rbins, rvals = self.radial_sampling(rbins=rbins, rvals=rvals, dr=dr)
        r_min = rbins[0] if r_min is None else r_min
        r_max = rbins[-1] if r_max is None else r_max
        idx_a = 0 if r_min <= rbins[0] else np.argmax(rbins >= r_min)
        idx_b = rbins.size if r_max >= rbins[-1] else np.argmin(rbins <= r_max)
        rbins, rvals = self.radial_sampling(rbins=rbins[idx_a:idx_b])

        # Cycle through and deproject the spectra.
        spectra = []
        for r_min, r_max in zip(rbins[:-1], rbins[1:]):
            if unit.lower() == 'jy' or unit.lower() == 'mjy':
                func = self.integrated_spectrum
                spectra += [func(r_min=r_min, r_max=r_max, dr=dr, x0=x0, y0=y0,
                                 inc=inc, PA=PA, z0=z0, psi=psi, z1=z1,
                                 phi=phi, z_func=z_func, mstar=mstar,
                                 dist=dist, resample=resample,
                                 beam_spacing=beam_spacing, PA_min=PA_min,
                                 PA_max=PA_max, exclude_PA=exclude_PA,
                                 abs_PA=abs_PA, mask_frame=mask_frame,
                                 assume_correlated=assume_correlated,
                                 mask=mask, shadowed=shadowed)]
            else:
                func = self.average_spectrum
                spectra += [func(r_min=r_min, r_max=r_max, dr=dr, x0=x0, y0=y0,
                                 inc=inc, PA=PA, z0=z0, psi=psi, z1=z1,
                                 phi=phi, z_func=z_func, mstar=mstar,
                                 dist=dist, resample=resample,
                                 beam_spacing=beam_spacing, PA_min=PA_min,
                                 PA_max=PA_max, exclude_PA=exclude_PA,
                                 abs_PA=abs_PA, mask=mask,
                                 assume_correlated=assume_correlated,
                                 mask_frame=mask_frame, unit=unit,
                                 shadowed=shadowed)]
        return rvals, np.squeeze(spectra)

    def radial_profile(self, rvals=None, rbins=None, dr=None,
                       unit='Jy/beam m/s', x0=0.0, y0=0.0, inc=0.0, PA=0.0,
                       z0=0.0, psi=1.0, z1=0.0, phi=1.0, z_func=None,
                       mstar=1.0, dist=100., resample=1, beam_spacing=False,
                       r_min=None, r_max=None, PA_min=None, PA_max=None,
                       exclude_PA=False, abs_PA=False, mask_frame='disk',
                       velo_range=None, assume_correlated=True, shadowed=True):
        """
        Generate a radial profile from shifted and stacked spectra. There are
        different ways to collapse the spectrum into a single value using the
        ``unit`` argument. Possible units for the flux (density) are:

            - ``'mJy/beam'``
            - ``'Jy/beam'``
            - ``'mK'``
            - ``'K'``
            - ``'mJy'``
            - ``'Jy'``

        where ``'/beam'`` is equivalent to ``'/pix'`` if not beam information
        is found in the FITS header. For the velocity we have:

            - ``'m/s'``
            - ``'km/s'``

        Any unit can be made up of these components is possible.
        All conversions from [Jy/beam] to [K] are performed using the
        Rayleigh-Jeans approximation. For other units, or to develop more
        sophisticated statistics for the collapsed line profiles, use the
        ``radial_spectra`` function.

        Args:
            rvals (Optional[floats]): Array of bin centres for the profile in
                [arcsec]. You need only specify one of ``rvals`` and ``rbins``.
            rbins (Optional[floats]): Array of bin edges for the profile in
                [arcsec]. You need only specify one of ``rvals`` and ``rbins``.
            dr (Optional[float]): Width of the radial bins in [arcsec] to
                use if neither ``rvals`` nor ``rbins`` is set. Default is 1/4
                of the beam major axis.
            unit (Optional[str]): Unit for the y-axis of the profile, as
                in the function description.
            x0 (Optional[float]): Source center offset along the x-axis in
                [arcsec].
            y0 (Optional[float]): Source center offset along the y-axis in
                [arcsec].
            inc (Optional[float]): Inclination of the disk in [degrees].
            PA (Optional[float]): Position angle of the disk in [degrees],
                measured east-of-north towards the redshifted major axis.
            z0 (Optional[float]): Emission height in [arcsec] at a radius of
                1".
            psi (Optional[float]): Flaring angle of the emission surface.
            z1 (Optional[float]): Correction to emission height at 1" in
                [arcsec].
            phi (Optional[float]): Flaring angle correction term.
            z_func (Optional[function]): A function which provides
                :math:`z(r)`. Note that no checking will occur to make sure
                this is a valid function.
            mstar (Optional[float]): Stellar mass in [Msun].
            dist (Optional[float]): Distance to the source in [pc].
            resample(Optional[float/int]): Resampling parameter for the
                deprojected spectrum. An integer specifies an average of that
                many channels, while a float specifies the desired channel
                width. Default is ``resample=1``.
            beam_spacing(Optional[bool]): When extracting the annuli, whether
                to choose spatially independent pixels or not.
            r_min (Optional[float]): Inner radius in [arcsec] of the region to
                integrate. The value used will be greater than or equal to
                ``r_min``.
            r_max (Optional[float]): Outer radius in [arcsec] of the region to
                integrate. The value used will be less than or equal to
                ``r_max``.
            PA_min (Optional[float]): Minimum polar angle to include in the
                annulus in [degrees]. Note that the polar angle is measured in
                the disk-frame, unlike the position angle which is measured in
                the sky-plane.
            PA_max (Optional[float]): Maximum polar angleto include in the
                annulus in [degrees]. Note that the polar angle is measured in
                the disk-frame, unlike the position angle which is measured in
                the sky-plane.
            exclude_PA (Optional[bool]): Whether to exclude pixels where
                ``PA_min <= PA_pix <= PA_max``.
            abs_PA (Optional[bool]): If ``True``, take the absolute value of
                the polar angle such that it runs from 0 [deg] to 180 [deg].
            mask_frame (Optional[str]): Which frame the radial and azimuthal
                mask is specified in, either ``'disk'`` or ``'sky'``.
            velo_range (Optional[tuple]): A tuple containing the spectral
                range to integrate if required for the provided ``unit``. Can
                either be a string, including units, or as channel integers.
            assume_correlated (Optional[bool]): Whether to treat the spectra
                which are stacked as correlated, by default this is
                ``True``. If ``False``, the uncertainty will be estimated using
                Poisson statistics, otherwise the uncertainty is just the
                standard deviation of each velocity bin.
            unit (Optional[str]): Desired unit of the output profile.

        Returns:
            Arrays of the bin centers in [arcsec], the profile value in the
            requested units and the associated uncertainties.
        """

        # If shifting not available, change function.
        if self.data.ndim == 2:
            return self._radial_profile_2D(rvals=rvals, rbins=rbins, dr=dr,
                                           x0=x0, y0=y0, inc=inc, PA=PA, z0=z0,
                                           psi=psi, z1=z1, phi=phi,
                                           z_func=z_func, r_min=r_min,
                                           r_max=r_max, PA_min=PA_min,
                                           PA_max=PA_max, abs_PA=abs_PA,
                                           exclude_PA=exclude_PA,
                                           mask_frame=mask_frame,
                                           assume_correlated=assume_correlated,
                                           shadowed=shadowed)

        # Grab the spectra.
        _flux_unit, _velo_unit = imagecube._parse_unit(unit)
        out = self.radial_spectra(rvals=rvals, rbins=rbins, dr=dr,
                                  x0=x0, y0=y0, inc=inc, PA=PA, z0=z0, psi=psi,
                                  z1=z1, phi=phi, z_func=z_func, mstar=mstar,
                                  dist=dist, resample=resample,
                                  beam_spacing=beam_spacing, r_min=r_min,
                                  r_max=r_max, PA_min=PA_min, PA_max=PA_max,
                                  exclude_PA=exclude_PA, abs_PA=abs_PA,
                                  mask_frame=mask_frame,
                                  assume_correlated=assume_correlated,
                                  unit=_flux_unit, shadowed=shadowed)
        rvals, spectra = out

        # Collapse the spectra to a radial profile.
        if _velo_unit is not None:
            scale = 1e0 if _velo_unit == 'm/s' else 1e-3
            chans = self._parse_channel(velo_range)
            profile = np.array([np.trapz(s[1][chans[0]:chans[1]+1],
                                         s[0][chans[0]:chans[1]+1] * scale)
                                for s in spectra])
        else:
            profile = np.nanmax(spectra[:, 1], axis=-1)
        if profile.size != rvals.size:
            raise ValueError("Mismatch in x and y values.")

        # Basic approximation of uncertainty.
        if _velo_unit is not None:
            sigma = np.mean(np.diff(spectra[:, 0], axis=-1), axis=-1) * scale
            sigma = spectra[:, 2, chans[0]:chans[1]+1]**2 * sigma[:, None]**2
            sigma = np.sum(sigma, axis=-1)**0.5
        else:
            sigma = np.argmax(spectra[:, 1], axis=-1)
            sigma = np.array([f[i] for f, i in zip(spectra[:, 2], sigma)])
        return rvals, profile, sigma

    def _parse_channel(self, unit):
        """Return the channel numbers based on the provided input."""
        _units = []
        if unit is None:
            return 0, self.velax.size-1
        for u in unit:
            if isinstance(u, int):
                _units += [u]
            elif isinstance(u, float):
                _units += [abs(self.velax - u).argmin()]
            elif isinstance(u, str):
                u = u.lower()
                if 'km/s' in u:
                    _velo = float(u.replace('km/s', '')) * 1e3
                    _units += [abs(self.velax - _velo).argmin()]
                elif 'm/s' in u:
                    _velo = float(u.replace('m/s', ''))
                    _units += [abs(self.velax - _velo).argmin()]
            else:
                raise ValueError("Unrecognised `velo_range` unit.")
        return int(min(_units)), int(max(_units))

    @staticmethod
    def _parse_unit(unit):
        """Return the flux and velocity units for integrating spectra."""
        try:
            flux, velo = unit.split(' ')
            velo = velo.lower()
        except ValueError:
            flux, velo = unit, None
        flux = flux.lower().replace('/pix', '/beam')
        if flux.lower() not in ['mjy', 'jy', 'mk', 'k', 'mjy/beam', 'jy/beam']:
            raise ValueError("Unknown flux unit: {}.".format(flux))
        if velo is not None and velo.lower() not in ['m/s', 'km/s']:
            raise ValueError("Unknown velocity unit: {}".format(velo))
        if velo is not None:
            velo = velo.lower()
        return flux.lower(), velo

    def _test_bunit(self):
        """Test to make sure the attached BUNIT value is valid."""
        try:
            bunit, vunit = self.bunit.lower().split(' ')
        except:
            bunit, vunit = self.bunit.lower(), ''
        bunit = bunit.replace('/pix', '/beam')
        if bunit not in ['jy/beam', 'mjy/beam', 'k', 'mk', 'm/s', 'km/s']:
            raise ValueError("Unknown 'BUNIT' value " +
                             "{}. ".format(self.header['bunit']) +
                             "Please provide `bunit`.")
        if vunit not in ['', 'km/s', 'm/s']:
            raise ValueError("Unknown 'BUNIT' value " +
                             "{}. ".format(self.header['bunit']) +
                             "Please provide `bunit`.")
        return bunit, vunit

    def _test_2D(self):
        """Check to see if the cube is 3D and can use shifting functions."""
        if self.data.ndim == 2:
            raise ValueError("Cube is only 2D. Shifting not available.")

    def _radial_profile_2D(self, rvals=None, rbins=None, dr=None, x0=0.0,
                           y0=0.0, inc=0.0, PA=0.0, z0=0.0, psi=1.0, z1=0.0,
                           phi=1.0, z_func=None, r_min=None, r_max=None,
                           PA_min=None, PA_max=None, exclude_PA=False,
                           abs_PA=False, mask_frame='disk',
                           assume_correlated=False, percentiles=False,
                           shadowed=True):
        """
        Returns the radial profile if `self.data.ndim == 2`, i.e., if shifting
        cannot be performed. Uses all the same parameters, but does not do any
        of the shifting and ignores the units. If this is called directly then
        there are several specific options.

        Args:
            percentiles (Optional[bool]): Use the 16th to 84th percentil of the
                bin distribution to estimate uncertainties rather than the
                standard deviation.

        Returns:
            Three 1D arrays with ``x``, ``y`` and ``dy`` for plotting.
        """

        # Warning message.
        if self.verbose:
            print("WARNING: Attached data is not 3D, so shifting cannot be " +
                  "applied.\n\t Reverting to standard azimuthal averaging; " +
                  "will ignore `unit` argument.")

        # Calculate the mask.
        rbins, rvals = self.radial_sampling(rbins=rbins, rvals=rvals, dr=dr)
        mask = self.get_mask(r_min=rbins[0], r_max=rbins[-1], PA_min=PA_min,
                             PA_max=PA_max, exclude_PA=exclude_PA,
                             abs_PA=abs_PA, mask_frame=mask_frame, x0=x0,
                             y0=y0, inc=inc, PA=PA, z0=z0, psi=psi, z1=z1,
                             phi=phi, z_func=z_func, shadowed=shadowed)
        if mask.shape != self.data.shape:
            raise ValueError("Mismatch in mask and data shape.")
        mask = mask.flatten()

        # Deprojection of the disk coordinates.
        rpnts = self.disk_coords(x0=x0, y0=y0, inc=inc, PA=PA, z0=z0, psi=psi,
                                 z1=z1, phi=phi, z_func=z_func,
                                 shadowed=shadowed)[0]
        if rpnts.shape != self.data.shape:
            raise ValueError("Mismatch in rvals and data shape.")
        rpnts = rpnts.flatten()

        # Account for the number of independent beams.
        if assume_correlated:
            nbeams = 2.0 * np.pi * rvals / self.bmaj
        else:
            nbeams = 1.0

        # Radial binning.
        rpnts = rpnts[mask]
        toavg = self.data.flatten()[mask]
        ridxs = np.digitize(rpnts, rbins)

        # Averaging.
        if percentiles:
            rstat = np.array([np.percentile(toavg[ridxs == r], [16, 50, 84])
                              for r in range(1, rbins.size)]).T
            ravgs = rstat[1]
            rstds = np.array([rstat[1] - rstat[0], rstat[2] - rstat[1]])
            rstds /= np.sqrt(nbeams)[None, :]
        else:
            ravgs = np.array([np.mean(toavg[ridxs == r])
                              for r in range(1, rbins.size)])
            rstds = np.array([np.std(toavg[ridxs == r])
                              for r in range(1, rbins.size)])
            rstds /= np.sqrt(nbeams)

        return rvals, ravgs, rstds

    def shifted_cube(self, inc, PA, mstar, dist, x0=0.0, y0=0.0, z0=0.0,
                     psi=1.0, z1=0.0, phi=1.0, z_func=None, r_min=None,
                     r_max=None, fill_val=np.nan, save=False, shadowed=True):
        """
        Apply the velocity shift to each pixel and return the cube, or save as
        as new FITS file. This would be useful if you want to create moment
        maps of the data where you want to integrate over a specific velocity
        range without having to worry about the Keplerian rotation in the disk.

        Args:
            inc (float): Inclination of the disk in [degrees].
            PA (float): Position angle of the disk in [degrees],
                measured east-of-north towards the redshifted major axis.
            mstar (Optional[float]): Stellar mass in [Msun].
            dist (Optional[float]): Distance to the source in [pc].
            z0 (Optional[float]): Emission height in [arcsec] at a radius of
                1".
            psi (Optional[float]): Flaring angle of the emission surface.
            z1 (Optional[float]): Correction to emission height at 1" in
                [arcsec].
            phi (Optional[float]): Flaring angle correction term.
            r_min (Optional[float]): The inner radius in [arcsec] to shift.
            r_max (Optional[float]): The outer radius in [arcsec] to shift.

        Returns:
            The shifted data cube.
        """

        # Radial positions.
        rvals, tvals, _ = self.disk_coords(x0=x0, y0=y0, inc=inc, PA=PA,
                                           z0=z0, psi=psi, z1=z1, phi=phi,
                                           z_func=z_func, shadowed=shadowed)
        r_min = 0.0 if r_min is None else r_min
        r_max = rvals.max() if r_max is None else r_max
        mask = np.logical_and(rvals >= r_min, rvals <= r_max)

        # Projected velocity.
        vkep = self._keplerian(rpnts=rvals, mstar=mstar, dist=dist, inc=inc,
                               z0=z0, psi=psi, z1=z1, phi=phi, z_func=z_func)
        vkep *= np.cos(tvals)
        if vkep.shape != mask.shape:
            raise ValueError("Velocity map incorrect shape.")

        # Shift each pixel.
        from scipy.interpolate import interp1d
        shifted = np.empty(self.data.shape)
        for y in range(self.nypix):
            for x in range(self.nxpix):
                if mask[y, x]:
                    shifted[:, y, x] = interp1d(self.velax - vkep[y, x],
                                                self.data[:, y, x],
                                                bounds_error=False)(self.velax)
        assert shifted.shape == self.data.shape, "Wrong shape of shifted cube."

        if save:
            if isinstance(save, str):
                output = save
            else:
                output = self.path.replace('.fits', '_shifted.fits')
            fits.writeto(output, shifted, self.header)
        return shifted

    def find_center(self, dx=None, dy=None, Nx=None, Ny=None, mask=None,
                    v_min=None, v_max=None, spectrum='avg', SNR='peak',
                    normalize=True, **kwargs):
        """
        Find the source center (assuming the disk is azimuthally symmetric) by
        calculating the SNR of the averaged spectrum by varying the source
        center, ``(x0, y0)``.

        Args:
            dx (Optional[float]): Maximum offset to consider in the `x`
                direction in [arcsec]. Default is one beam FWHM.
            dy (Optional[float]): Maximum offset to consider in the `y`
                direction in [arcsec]. Default is one beam FWHM.
            Nx (Optional[int]): Number of samples to take along the `x`
                direction. Default results in roughtly pixel spacing.
            Ny (Optional[int]): Number of samples to take along the `y`
                direction. Default results in roughtly pixel spacing.
            mask (Optional[array]): Boolean mask of channels to use when
                calculating the integrated flux or RMS noise.
            v_min (Optional[float]): Minimum velocity in [m/s] to consider if
                an explicit mask is not provided.
            v_max (Optional[float]): Maximum velocity in [m/s] to consider if
                an explicit mask is not provided.
            spectrum (Optional[str]): Type of spectrum to consider, either the
                integrated spectrum with ``'int'``, or the average spectrum
                with ``'avg'``.
            SNR (Optional[str]): Type of signal-to-noise definition to use.
                Either ``'int'`` to use the integrated flux density as the
                signal, or ``'peak'`` to use the maximum value.
            normalize (Optional[bool]): Whether to normalize the SNR map
                relative to the SNR at ``(x0, y0) = (0, 0)``.

        Returns:
            The axes of the grid search, ``x0s`` and ``y0s``, as well as the
            2D array of SNR values, ``SNR``.
        """

        # Verify the SNR method.
        spectrum = spectrum.lower()
        if spectrum == 'avg':
            spectrum_func = self.average_spectrum
        elif spectrum == 'int':
            spectrum_func = self.integrated_spectrum
        else:
            raise ValueError("`spectrum` must be 'avg' or 'int'.")
        SNR = SNR.lower()
        if SNR == 'int':
            SNR_func = self._integrated_SNR
        elif SNR == 'peak':
            SNR_func = self._peak_SNR
        else:
            raise ValueError("`SNR` must be 'int' or 'peak'.")

        # Define the axes to search.
        dx = self.bmaj if dx is None else dx
        dy = self.bmaj if dy is None else dy
        Nx = int(2. * dx / self.dpix) if Nx is None else Nx
        Ny = int(2. * dy / self.dpix) if Ny is None else Ny
        x0s = np.linspace(-dx, dx, Nx)
        y0s = np.linspace(-dy, dy, Ny)
        SNR = np.zeros((Ny, Nx))

        # Empty the kwargs.
        _ = kwargs.pop('x0', np.nan)
        _ = kwargs.pop('y0', np.nan)

        # Define the mask.
        x, _, _ = spectrum_func(**kwargs)
        v_min = np.percentile(x, [40.])[0] if v_min is None else v_min
        v_max = np.percentile(x, [60.])[0] if v_max is None else v_max
        mask = np.logical_and(x >= v_min, x <= v_max) if mask is None else mask
        if mask.size != x.size:
            raise ValueError("`mask` is not the same size as expected v-axis.")

        # Loop through the possible centers.
        for i, x0 in enumerate(x0s):
            for j, y0 in enumerate(y0s):
                try:
                    x, y, dy = spectrum_func(x0=x0, y0=y0, **kwargs)
                    SNR[j, i] = SNR_func(x, y, dy, mask)
                except ValueError:
                    SNR[j, i] = np.nan

        # Determine the optimum position.
        self._plot_center(x0s, y0s, SNR, normalize)
        return x0s, y0s, SNR

    def _integrated_SNR(self, x, y, dy, mask):
        """SNR based on the integrated spectrum."""
        y_tmp = np.where(np.logical_and(mask, np.isfinite(y)), y, 0.0)
        return np.trapz(y_tmp, x=x) / np.nanmean(dy[~mask])

    def _peak_SNR(self, x, y, dy, mask):
        """SNR based on the peak of the spectrum."""
        y_tmp = np.where(np.logical_and(mask, np.isfinite(y)), y, 0.0)
        return np.max(y_tmp) / np.nanmean(dy[~mask])

    def _keplerian(self, rpnts, mstar=1.0, dist=100., inc=90.0, z0=0.0,
                   psi=1.0, z1=0.0, phi=1.0, z_func=None):
        """
        Return a Keplerian rotation profile [m/s] at rpnts [arcsec].

        Args:
            rpnts (ndarray/float): Radial locations in [arcsec] to calculate
                the Keplerian rotation curve at.
            mstar (float): Mass of the central star in [Msun].
            dist (float): Distance to the source in [pc].
            inc (Optional[float]): Inclination of the source in [deg]. If not
                provided, will return the unprojected value.
            z0 (Optional[float]): Aspect ratio at 1" for the emission surface.
                To get the far side of the disk, make this number negative.
            psi (Optional[float]): Flaring angle for the emission surface.
            z1 (Optional[float]): Aspect ratio correction term at 1" for the
                emission surface. Should be opposite sign to z0.
            phi (Optional[float]): Flaring angle correction term for the
                emission surface.
            z_func (Optional[function]): A function which provides
                :math:`z(r)`. Note that no checking will occur to make sure
                this is a valid function.

        Returns:
            vkep (ndarray/float): Keplerian rotation curve [m/s] at the
                specified radial locations.
        """
        rpnts = np.squeeze(rpnts)
        if z_func is None:
            zvals = z0 * np.power(rpnts, psi) + z1 * np.power(rpnts, phi)
        else:
            zvals = z_func(rpnts)
        r_m, z_m = rpnts * dist * sc.au, zvals * dist * sc.au
        vkep = sc.G * mstar * 1.988e30 * np.power(r_m, 2.0)
        vkep = np.sqrt(vkep / np.power(np.hypot(r_m, z_m), 3.0))
        return vkep * np.sin(abs(np.radians(inc)))

    # -- Inferring Velocity Profiles -- #

    def get_vlos(self, rvals=None, rbins=None, r_min=None, r_max=None,
                 PA_min=None, PA_max=None, exclude_PA=False, abs_PA=False,
                 x0=0.0, y0=0.0, inc=0.0, PA=0.0, z0=0.0, psi=1.0, z1=0.0,
                 phi=1.0, z_func=None, mstar=None, dist=None, mask=None,
                 mask_frame='disk', beam_spacing=True, annulus_kwargs=None,
                 get_vlos_kwargs=None, shadowed=True):
        """
        Infer the rotational and radial velocity profiles from the data
        following the approach described in `Teague et al. (2018)`_. The cube
        will be split into annuli, with the `get_vlos()` function from
        `annulus` being used to infer the rotational (and radial) velocities.
        Note that to return also radial velocities, you must include
        ``get_vlos_kwargs=dict(fit_vrad=True)``.

        .. _Teague et al. 2018: https://ui.adsabs.harvard.edu/abs/2018ApJ...868..113T/abstract

        Args:
            rvals (Optional[floats]): Array of bin centres for the profile in
                [arcsec]. You need only specify one of ``rvals`` and ``rbins``.
            rbins (Optional[floats]): Array of bin edges for the profile in
                [arcsec]. You need only specify one of ``rvals`` and ``rbins``.
            r_min (float): Minimum midplane radius of the annuli in [arcsec].
            r_max (float): Maximum midplane radius of the annuli in [arcsec].
            PA_min (Optional[float]): Minimum polar angle of the segment of the
                annulus in [degrees]. Note this is the polar angle, not the
                position angle.
            PA_max (Optional[float]): Maximum polar angle of the segment of the
                annulus in [degrees]. Note this is the polar angle, not the
                position angle.
            exclude_PA (Optional[bool]): If ``True``, exclude the provided
                polar angle range rather than include.
            abs_PA (Optional[bool]): If ``True``, take the absolute value of
                the polar angle such that it runs from 0 [deg] to 180 [deg].
            x0 (Optional[float]): Source right ascension offset [arcsec].
            y0 (Optional[float]): Source declination offset [arcsec].
            inc (Optional[float]): Source inclination [deg].
            PA (Optional[float]): Source position angle [deg]. Measured
                between north and the red-shifted semi-major axis in an
                easterly direction.
            z0 (Optional[float]): Aspect ratio at 1" for the emission surface.
                To get the far side of the disk, make this number negative.
            psi (Optional[float]): Flaring angle for the emission surface.
            z1 (Optional[float]): Aspect ratio correction term at 1" for the
                emission surface. Should be opposite sign to z0.
            phi (Optional[float]): Flaring angle correction term for the
                emission surface.
            z_func (Optional[function]): A function which provides z(r). Note
                that no checking will occur to make sure this is a valid
                function.
            mstar (Optional[float]): Stellar mass of the central star in [Msun]
                to calculate the  starting positions for the MCMC. If
                specified, must also provide ``dist``.
            dist (Optional[float]): Source distance in [pc] to use to calculate
                the starting positions for the MCMC. If specified, must also
                provide ``mstar``.
            mask (Optional[ndarray]): A 2D array mask which matches the shape
                of the data.
            mask_frame (Optional[str]): Coordinate frame for the mask. Either
                ``'disk'`` or ``'sky'``. If ``disk`` coordinates are used then
                the inclination and position angle of the mask are set to zero.
            beam_spacing (Optional[bool/float]): If True, randomly sample the
                annulus such that each pixel is at least a beam FWHM apart. A
                number can also be used in place of a boolean which will
                describe the number of beam FWHMs to separate each sample by.
            annulus_kwargs (Optional[dict]): Kwargs to pass to ``get_annulus``.
            get_vlos_kwargs (Optional[dict]): Kwargs to pass to
                ``annulus.get_vlos``.

        Returns:
            The radial sampling of the annuli, ``rpnts``, and a list of the
            values returned from ``annulus.get_vlos``.
        """

        # Check the input variables.
        if mstar is not None and dist is None:
            raise ValueError("Must specify both `mstar` and `dist`.")
        if dist is not None and mstar is None:
            raise ValueError("Must specify both `mstar` and `dist`.")

        # Get the radial sampling.
        rbins, rpnts = self.radial_sampling(rbins=rbins, rvals=rvals)
        r_min = rbins[0] if r_min is None else r_min
        r_max = rbins[-1] if r_max is None else r_max
        r_mask = np.logical_and(rbins >= r_min, rbins <= r_max)
        rbins, rpnts = self.radial_sampling(rbins=rbins[r_mask])

        # Set the defauls for the get_vlos() function.
        get_vlos_kwargs = {} if get_vlos_kwargs is None else get_vlos_kwargs
        get_vlos_kwargs['plots'] = get_vlos_kwargs.pop('plots', 'none')

        returns = []
        for ridx in range(rpnts.size):
            annulus = self.get_annulus(r_min=rbins[ridx], r_max=rbins[ridx+1],
                                       PA_min=PA_min, PA_max=PA_max,
                                       exclude_PA=exclude_PA, abs_PA=abs_PA,
                                       x0=x0, y0=y0, inc=inc, PA=PA, z0=z0,
                                       psi=psi, z1=z1, phi=phi, z_func=z_func,
                                       mask=mask, beam_spacing=beam_spacing,
                                       shadowed=shadowed)

            # Starting positions if a velocity profile is given.
            if mstar is not None:
                vrot = self._keplerian(rpnts=rpnts[ridx], mstar=mstar,
                                       dist=dist, inc=inc, z0=z0, psi=psi,
                                       z1=z1, phi=phi, z_func=z_func)
                vrad = 0.0
                rms = self.estimate_RMS()
                ln_sig = np.log(np.std(annulus.spectra))
                ln_rho = np.log(150.)
                get_vlos_kwargs['p0'] = [vrot, vrad, rms, ln_sig, ln_rho]
            else:
                get_vlos_kwargs['p0'] = None
            returns += [annulus.get_vlos(**get_vlos_kwargs)]
        return rpnts, np.squeeze(returns)

    # -- Annulus Masking Functions -- #

    def get_annulus(self, r_min, r_max, PA_min=None, PA_max=None,
                    exclude_PA=False, abs_PA=False, x0=0.0, y0=0.0, inc=0.0,
                    PA=0.0, z0=0.0, psi=1.0, z1=0.0, phi=1.0, z_func=None,
                    mask=None, mask_frame='disk', beam_spacing=True,
                    annulus_kwargs=None, shadowed=True):
        """
        Return an annulus (or section of), of spectra and their polar angles.
        Can select spatially independent pixels within the annulus, however as
        this is random, each draw will be different.

        Args:
            r_min (float): Minimum midplane radius of the annulus in [arcsec].
            r_max (float): Maximum midplane radius of the annulus in [arcsec].
            PA_min (Optional[float]): Minimum polar angle of the segment of the
                annulus in [degrees]. Note this is the polar angle, not the
                position angle.
            PA_max (Optional[float]): Maximum polar angle of the segment of the
                annulus in [degrees]. Note this is the polar angle, not the
                position angle.
            exclude_PA (Optional[bool]): If ``True``, exclude the provided
                polar angle range rather than include.
            abs_PA (Optional[bool]): If ``True``, take the absolute value of
                the polar angle such that it runs from 0 [deg] to 180 [deg].
            x0 (Optional[float]): Source right ascension offset [arcsec].
            y0 (Optional[float]): Source declination offset [arcsec].
            inc (Optional[float]): Source inclination [deg].
            PA (Optional[float]): Source position angle [deg]. Measured
                between north and the red-shifted semi-major axis in an
                easterly direction.
            z0 (Optional[float]): Aspect ratio at 1" for the emission surface.
                To get the far side of the disk, make this number negative.
            psi (Optional[float]): Flaring angle for the emission surface.
            z1 (Optional[float]): Aspect ratio correction term at 1" for the
                emission surface. Should be opposite sign to z0.
            phi (Optional[float]): Flaring angle correction term for the
                emission surface.
            z_func (Optional[function]): A function which provides z(r). Note
                that no checking will occur to make sure this is a valid
                function.
            mask (Optional[ndarray]): A 2D array mask which matches the shape
                of the data.
            mask_frame (Optional[str]): Coordinate frame for the mask. Either
                ``'disk'`` or ``'sky'``. If ``disk`` coordinates are used then
                the inclination and position angle of the mask are set to zero.
            beam_spacing (Optional[bool/float]): If True, randomly sample the
                annulus such that each pixel is at least a beam FWHM apart. A
                number can also be used in place of a boolean which will
                describe the number of beam FWHMs to separate each sample by.

        Returns:
            If ``annulus=True``, will return an ``eddy.annulus`` instance,
            otherwise will be an array containing the polar angles of each
            spectrum in [degrees] and the array of spectra, ordered in
            increasing polar angle.
        """
        # Check is cube is 2D.
        self._test_2D()

        # Generate the mask and check it is the correct shape.
        if mask is None:
            mask = self.get_mask(r_min=r_min, r_max=r_max, exclude_r=False,
                                 PA_min=PA_min, PA_max=PA_max,
                                 exclude_PA=exclude_PA, abs_PA=abs_PA, x0=x0,
                                 y0=y0, inc=inc, PA=PA, z0=z0, psi=psi, z1=z1,
                                 phi=phi, z_func=z_func, mask_frame=mask_frame,
                                 shadowed=shadowed)
        if mask.shape != self.data[0].shape:
            raise ValueError("`mask` is incorrect shape.")
        mask = mask.flatten()

        # Flatten the data and get deprojected pixel coordinates.
        dvals = self.data.copy().reshape(self.data.shape[0], -1)
        rvals, tvals = self.disk_coords(x0=x0, y0=y0, inc=inc, PA=PA, z0=z0,
                                        psi=psi, z1=z1, phi=phi,
                                        z_func=z_func, shadowed=shadowed)[:2]
        rvals, tvals = rvals.flatten(), tvals.flatten()
        dvals, rvals, tvals = dvals[:, mask].T, rvals[mask], tvals[mask]

        # Apply the beam sampling.
        if beam_spacing:

            # Order the data in increase position angle.
            idxs = np.argsort(tvals)
            dvals, tvals = dvals[idxs], tvals[idxs]

            # Calculate the sampling rate.
            sampling = float(beam_spacing) * self.bmaj
            sampling /= np.mean(rvals) * np.median(np.diff(tvals))
            sampling = np.floor(sampling).astype('int')

            # If the sampling rate is above 1, start at a random location in
            # the array and sample at this rate, otherwise don't sample. This
            # happens at small radii, for example.
            if sampling > 1:
                start = np.random.randint(0, tvals.size)
                tvals = np.concatenate([tvals[start:], tvals[:start]])
                dvals = np.vstack([dvals[start:], dvals[:start]])
                tvals, dvals = tvals[::sampling], dvals[::sampling]

        # Return the annulus.
        annulus_kwargs = {} if annulus_kwargs is None else annulus_kwargs
        return annulus(spectra=dvals, theta=tvals, velax=self.velax,
                       **annulus_kwargs)

    def get_mask(self, r_min=None, r_max=None, exclude_r=False, PA_min=None,
                 PA_max=None, exclude_PA=False, abs_PA=False,
                 mask_frame='disk', x0=0.0, y0=0.0, inc=0.0, PA=0.0, z0=0.0,
                 psi=1.0, z1=0.0, phi=1.0, z_func=None, shadowed=True):
        """
        Returns a 2D mask for pixels in the given region. The mask can be
        specified in either disk-centric coordinates, ``mask_frame='disk'``,
        or on the sky, ``mask_frame='sky'``. If sky-frame coordinates are
        requested, the geometrical parameters (``inc``, ``PA``, ``z0``, etc.)
        are ignored, however the source offsets, ``x0``, ``y0``, are still
        considered.

        Args:
            r_min (Optional[float]): Minimum midplane radius of the annulus in
                [arcsec]. Defaults to minimum deprojected radius.
            r_max (Optional[float]): Maximum midplane radius of the annulus in
                [arcsec]. Defaults to the maximum deprojected radius.
            exclude_r (Optional[bool]): If ``True``, exclude the provided
                radial range rather than include.
            PA_min (Optional[float]): Minimum polar angle of the segment of the
                annulus in [degrees]. Note this is the polar angle, not the
                position angle.
            PA_max (Optional[float]): Maximum polar angle of the segment of the
                annulus in [degrees]. Note this is the polar angle, not the
                position angle.
            exclude_PA (Optional[bool]): If ``True``, exclude the provided
                polar angle range rather than include it.
            abs_PA (Optional[bool]): If ``True``, take the absolute value of
                the polar angle such that it runs from 0 [deg] to 180 [deg].
            x0 (Optional[float]): Source center offset along the x-axis in
                [arcsec].
            y0 (Optional[float]): Source center offset along the y-axis in
                [arcsec].
            inc (Optional[float]): Inclination of the disk in [degrees].
            PA (Optional[float]): Position angle of the disk in [degrees],
                measured east-of-north towards the redshifted major axis.
            z0 (Optional[float]): Emission height in [arcsec] at a radius of
                1".
            psi (Optional[float]): Flaring angle of the emission surface.
            z1 (Optional[float]): Correction to emission height at 1" in
                [arcsec].
            phi (Optional[float]): Flaring angle correction term.
            z_func (Optional[function]): A function which provides
                :math:`z(r)`. Note that no checking will occur to make sure
                this is a valid function.

        Returns:
            A 2D array mask matching the shape of a channel.
        """

        # Check the requested frame.
        mask_frame = mask_frame.lower()
        if mask_frame not in ['disk', 'sky']:
            raise ValueError("mask_frame must be 'disk' or 'sky'.")

        # Remove coordinates if in sky-frame.
        if mask_frame == 'sky':
            inc, PA = 0.0, 0.0
            z0, psi = 0.0, 1.0
            z1, phi = 0.0, 1.0
            z_func = None

        # Calculate pixel coordaintes.
        rvals, tvals = self.disk_coords(x0=x0, y0=y0, inc=inc, PA=PA, z0=z0,
                                        psi=psi, z1=z1, phi=phi, z_func=z_func,
                                        frame='cylindrical',
                                        shadowed=shadowed)[:2]
        tvals = abs(tvals) if abs_PA else tvals

        # Radial mask.
        r_min = np.nanmin(rvals) if r_min is None else r_min
        r_max = np.nanmax(rvals) if r_max is None else r_max
        if r_min >= r_max:
            raise ValueError("`r_min` must be smaller than `r_max`.")
        r_mask = np.logical_and(rvals >= r_min, rvals <= r_max)
        r_mask = ~r_mask if exclude_r else r_mask

        # Azimuthal mask.
        PA_min = np.nanmin(tvals) if PA_min is None else np.radians(PA_min)
        PA_max = np.nanmax(tvals) if PA_max is None else np.radians(PA_max)
        if PA_min >= PA_max:
            raise ValueError("`PA_min` must be smaller than `PA_max`.")
        PA_mask = np.logical_and(tvals >= PA_min, tvals <= PA_max)
        PA_mask = ~PA_mask if exclude_PA else PA_mask

        # Combine and return.
        mask = r_mask * PA_mask
        if np.sum(mask) == 0:
            raise ValueError("There are zero pixels in the mask.")
        return mask

    def radial_sampling(self, rbins=None, rvals=None, dr=None):
        """
        Return bins and bin center values. If the desired bin edges are known,
        will return the bin edges and vice versa. If neither are known will
        return default binning with the desired spacing.

        Args:
            rbins (Optional[list]): List of bin edges.
            rvals (Optional[list]): List of bin centers.
            dr (Optional[float]): Spacing of bin centers in [arcsec]. Defaults
                to a quarter of the beam major axis.

        Returns:
            rbins (list): List of bin edges.
            rpnts (list): List of bin centres.
        """
        if rbins is not None and rvals is not None:
            raise ValueError("Specify only 'rbins' or 'rvals', not both.")
        if rvals is not None:
            try:
                dr = np.diff(rvals)[0] * 0.5
            except IndexError:
                dr = 0.125 * self.bmaj
            rbins = np.linspace(rvals[0] - dr, rvals[-1] + dr, len(rvals) + 1)
        if rbins is not None:
            rvals = np.average([rbins[1:], rbins[:-1]], axis=0)
        else:
            dr = 0.25 * self.bmaj if dr is None else dr
            rbins = np.arange(0, self.xaxis.max(), dr)
            rvals = np.average([rbins[1:], rbins[:-1]], axis=0)
        return rbins, rvals

    def background_residual(self, x0=0.0, y0=0.0, inc=0.0, PA=0.0, z0=0.0,
                            psi=0.0, z1=0.0, phi=0.0, z_func=None, r_min=None,
                            r_max=None, PA_min=None, PA_max=None,
                            exclude_PA=False, abs_PA=False, mask_frame='disk',
                            interp1d_kw=None, background_only=False,
                            shadowed=True):
        """
        Return the residual from an azimuthally avearged background. This is
        most appropriate for exploring azimuthally asymmetric emission in
        either the zeroth moment (integrated intensity) or the peak brightness
        temperature maps. As such, this function only works for 2D data.

        The coordinates provided will be used to both build the azimuthally
        averaged profile (using the ``radial_profile`` function) and then
        project this onto the sky-plane. Any masking parameters used here will
        only be used when creating the azimuthally spectrum, but the residual
        with cover the entire data.

        Args:
            x0 (Optional[float]): Source right ascension offset [arcsec].
            y0 (Optional[float]): Source declination offset [arcsec].
            inc (Optional[float]): Source inclination [deg].
            PA (Optional[float]): Source position angle [deg]. Measured
                between north and the red-shifted semi-major axis in an
                easterly direction.
            z0 (Optional[float]): Aspect ratio at 1" for the emission surface.
                To get the far side of the disk, make this number negative.
            psi (Optional[float]): Flaring angle for the emission surface.
            z1 (Optional[float]): Aspect ratio correction term at 1" for the
                emission surface. Should be opposite sign to z0.
            phi (Optional[float]): Flaring angle correction term for the
                emission surface.
            z_func (Optional[function]): A function which provides z(r). Note
                that no checking will occur to make sure this is a valid
                function.
            r_min (Optional[float]): Inner radius in [arcsec] of the region to
                integrate. The value used will be greater than or equal to
                ``r_min``.
            r_max (Optional[float]): Outer radius in [arcsec] of the region to
                integrate. The value used will be less than or equal to
                ``r_max``.
            PA_min (Optional[float]): Minimum polar angle to include in the
                annulus in [degrees]. Note that the polar angle is measured in
                the disk-frame, unlike the position angle which is measured in
                the sky-plane.
            PA_max (Optional[float]): Maximum polar angleto include in the
                annulus in [degrees]. Note that the polar angle is measured in
                the disk-frame, unlike the position angle which is measured in
                the sky-plane.
            exclude_PA (Optional[bool]): Whether to exclude pixels where
                ``PA_min <= PA_pix <= PA_max``.
            abs_PA (Optional[bool]): If ``True``, take the absolute value of
                the polar angle such that it runs from 0 [deg] to 180 [deg].
            mask_frame (Optional[str]): Which frame the radial and azimuthal
                mask is specified in, either ``'disk'`` or ``'sky'``.
            interp1d_kw (Optional[dict]): Kwargs to pass to
                ``scipy.interpolate.interp1d``.
            background_only (Optional[bool]): If True, return only the
                azimuthally averaged background rather than the residual.
                Default is ``False``.

        Returns:
            residual (array): Residual between the data and the azimuthally
                averaged background. If ``background_only = True`` then this is
                just the azimuthally averaged background.
        """
        # Check if the attached data is 2D.
        if self.data.ndim != 2:
            raise ValueError("Cannot azimuthally average a 3D cube.")

        # Make the azimuthal profile.
        x, y, _ = self.radial_profile(x0=x0, y0=y0, inc=inc, PA=PA,
                                      z0=z0, phi=phi, z1=z1, psi=psi,
                                      z_func=z_func, r_min=r_min, r_max=r_max,
                                      PA_min=PA_min, PA_max=PA_max,
                                      exclude_PA=exclude_PA, abs_PA=abs_PA,
                                      mask_frame=mask_frame, shadowed=shadowed)

        # Build the interpolation function.
        from scipy.interpolate import interp1d
        interp1d_kw = interp1d_kw if interp1d_kw is not None else {}
        interp1d_kw['bounds_error'] = interp1d_kw.pop('bounds_error', False)
        interp1d_kw['fill_value'] = interp1d_kw.pop('fill_value', np.nan)
        avg = interp1d(x, y, **interp1d_kw)

        # Return the residual (or background if requested).
        background = avg(self.disk_coords(x0=x0, y0=y0, inc=inc, PA=PA,
                                          z0=z0, phi=phi, z1=z1, psi=psi,
                                          z_func=z_func, shadowed=shadowed)[0])
        return background if background_only else self.data - background

    # -- Deprojection Functions -- #

    def disk_coords(self, x0=0.0, y0=0.0, inc=0.0, PA=0.0, z0=0.0, psi=0.0,
                    z1=0.0, phi=0.0, z_func=None, frame='cylindrical',
                    shadowed=True, extend=2.0, oversample=2.0,
                    griddata_kw=None):
        r"""
        Get the disk coordinates given certain geometrical parameters and an
        emission surface. The emission surface is parameterized as a powerlaw
        profile:

        .. math::

            z(r) = z_0 \times \left(\frac{r}{1^{\prime\prime}}\right)^{\psi} +
            z_1 \times \left(\frac{r}{1^{\prime\prime}}\right)^{\varphi}

        Where both ``z0`` and ``z1`` are given in [arcsec]. For a razor thin
        disk, ``z0=0.0``, while for a conical disk, as described in `Rosenfeld
        et al. (2013)`_, ``psi=1.0``. Typically ``z1`` is not needed unless the
        data is exceptionally high SNR and well spatially resolved.

        It is also possible to override this parameterization and directly
        provide a user-defined ``z_func``. This allow for highly complex
        surfaces to be included. If this is provided, the other height
        parameters are ignored.

        .. _Rosenfeld et al. (2013): https://ui.adsabs.harvard.edu/abs/2013ApJ...774...16R/

        Args:
            x0 (Optional[float]): Source right ascension offset [arcsec].
            y0 (Optional[float]): Source declination offset [arcsec].
            inc (Optional[float]): Source inclination [deg].
            PA (Optional[float]): Source position angle [deg]. Measured
                between north and the red-shifted semi-major axis in an
                easterly direction.
            z0 (Optional[float]): Aspect ratio at 1" for the emission surface.
                To get the far side of the disk, make this number negative.
            psi (Optional[float]): Flaring angle for the emission surface.
            z1 (Optional[float]): Aspect ratio correction term at 1" for the
                emission surface. Should be opposite sign to ``z0``.
            phi (Optional[float]): Flaring angle correction term for the
                emission surface.
            z_func (Optional[function]): A function which provides
                :math:`z(r)`. Note that no checking will occur to make sure
                this is a valid function.
            frame (Optional[str]): Frame of reference for the returned
                coordinates. Either ``'polar'`` or ``'cartesian'``.

        Returns:
            Three coordinate arrays, either the cylindrical coordaintes,
            ``(r, theta, z)`` or cartestian coordinates, ``(x, y, z)``,
            depending on ``frame``.
        """

        # Check the input variables.

        frame = frame.lower()
        if frame not in ['cylindrical', 'cartesian']:
            raise ValueError("frame must be 'cylindrical' or 'cartesian'.")

        # Apply the inclination concention.
        inc = inc if inc < 90.0 else inc - 180.0

        # Define the emission surface function. Either use the simple double
        # power-law profile or the user-provied function.

        if z_func is None:
            def z_func(r):
                z = z0 * np.power(r, psi) + z1 * np.power(r, phi)
                if z0 >= 0.0:
                    return np.clip(z, a_min=0.0, a_max=None)
                return np.clip(z, a_min=None, a_max=0.0)

        # Calculate the pixel values.
        if shadowed:
            griddata_kw = {} if griddata_kw is None else griddata_kw
            r, t, z = self._get_shadowed_coords(x0, y0, inc, PA, z_func,
                                                extend, oversample,
                                                **griddata_kw)
        else:
            r, t, z = self._get_flared_coords(x0, y0, inc, PA, z_func)

        # Transform coordinate system.
        if frame == 'cylindrical':
            return r, t, z
        return r * np.cos(t), r * np.sin(t), z

    @staticmethod
    def _rotate_coords(x, y, PA):
        """Rotate (x, y) by PA [deg]."""
        x_rot = y * np.cos(np.radians(PA)) + x * np.sin(np.radians(PA))
        y_rot = x * np.cos(np.radians(PA)) - y * np.sin(np.radians(PA))
        return x_rot, y_rot

    @staticmethod
    def _deproject_coords(x, y, inc):
        """Deproject (x, y) by inc [deg]."""
        return x, y / np.cos(np.radians(inc))

    def _get_cart_sky_coords(self, x0, y0):
        """Return caresian sky coordinates in [arcsec, arcsec]."""
        return np.meshgrid(self.xaxis - x0, self.yaxis - y0)

    def _get_polar_sky_coords(self, x0, y0):
        """Return polar sky coordinates in [arcsec, radians]."""
        x_sky, y_sky = self._get_cart_sky_coords(x0, y0)
        return np.hypot(y_sky, x_sky), np.arctan2(x_sky, y_sky)

    def _get_midplane_cart_coords(self, x0, y0, inc, PA):
        """Return cartesian coordaintes of midplane in [arcsec, arcsec]."""
        x_sky, y_sky = self._get_cart_sky_coords(x0, y0)
        x_rot, y_rot = imagecube._rotate_coords(x_sky, y_sky, PA)
        return imagecube._deproject_coords(x_rot, y_rot, inc)

    def _get_midplane_polar_coords(self, x0, y0, inc, PA):
        """Return the polar coordinates of midplane in [arcsec, radians]."""
        x_mid, y_mid = self._get_midplane_cart_coords(x0, y0, inc, PA)
        return np.hypot(y_mid, x_mid), np.arctan2(y_mid, x_mid)

    def _get_flared_coords(self, x0, y0, inc, PA, z_func):
        """Return cylindrical coordinates of surface in [arcsec, radians]."""
        x_mid, y_mid = self._get_midplane_cart_coords(x0, y0, inc, PA)
        r_tmp, t_tmp = np.hypot(x_mid, y_mid), np.arctan2(y_mid, x_mid)
        for _ in range(10):
            y_tmp = y_mid + z_func(r_tmp) * np.tan(np.radians(inc))
            r_tmp = np.hypot(y_tmp, x_mid)
            t_tmp = np.arctan2(y_tmp, x_mid)
        return r_tmp, t_tmp, z_func(r_tmp)

    def _get_shadowed_coords(self, x0, y0, inc, PA, z_func, extend=2.0,
                             oversample=2.0, griddata_kw=None):
        """
        Return cyclindrical coords of surface in [arcsec, rad, arcsec] but
        using a slightly slower method that deals better with large gradients
        in the emission surface.

        Args:
            x0 (Optional[float]): Source right ascension offset [arcsec].
            y0 (Optional[float]): Source declination offset [arcsec].
            inc (Optional[float]): Source inclination [deg].
            PA (Optional[float]): Source position angle [deg]. Measured
                between north and the red-shifted semi-major axis in an
                easterly direction.
            z_func (Optional[function]): A function which provides
                :math:`z(r)`. Note that no checking will occur to make sure
                this is a valid function.
            extend (Optional[float]): When calculating the disk-frame
                coordinates, extend the axes by this amount. A larger area is
                necessary as for large inclinations as the projected distance
                along the minor axis will be compressed.
            oversample (Optional[float]): Oversample the axes by this factor. A
                larger value will give a more precise deprojection at the cost
                of computation time.
            griddata_kw (Optional[dict]): Any kwargs to be passed to
                ``griddata`` which performs the interpolation.

        Returns:
            Three coordinate arrays, either the cylindrical coordaintes,
            ``(r, theta, z)`` or cartestian coordinates, ``(x, y, z)``,
            depending on ``frame``.
        """

        # Make the disk-frame coordinates.
        diskframe_coords = self._get_diskframe_coords(extend, oversample)
        xdisk, ydisk, rdisk, tdisk = diskframe_coords
        zdisk = z_func(rdisk)

        # Incline the disk.
        inc = np.radians(inc)
        x_dep = xdisk
        y_dep = ydisk * np.cos(inc) - zdisk * np.sin(inc)

        # Remove shadowed pixels.
        if inc < 0.0:
            y_dep = np.maximum.accumulate(y_dep, axis=0)
        else:
            y_dep = np.minimum.accumulate(y_dep[::-1], axis=0)[::-1]

        # Rotate and the disk.
        x_rot, y_rot = imagecube._rotate_coords(x_dep, y_dep, PA)
        x_rot, y_rot = x_rot + x0, y_rot + y0

        # Grid the disk.
        from scipy.interpolate import griddata
        disk = (x_rot.flatten(), y_rot.flatten())
        grid = (self.xaxis[None, :], self.yaxis[:, None])
        griddata_kw = {} if griddata_kw is None else griddata_kw
        griddata_kw['method'] = griddata_kw.get('method', 'nearest')
        r_obs = griddata(disk, rdisk.flatten(), grid, **griddata_kw)
        t_obs = griddata(disk, tdisk.flatten(), grid, **griddata_kw)
        return r_obs, t_obs, z_func(r_obs)

    def _get_diskframe_coords(self, extend=2.0, oversample=0.5):
        """Disk-frame coordinates based on the cube axes."""
        x_disk = np.linspace(extend * self.xaxis[0], extend * self.xaxis[-1],
                             int(self.nxpix * oversample))[::-1]
        y_disk = np.linspace(extend * self.yaxis[0], extend * self.yaxis[-1],
                             int(self.nypix * oversample))
        x_disk, y_disk = np.meshgrid(x_disk, y_disk)
        r_disk = np.hypot(x_disk, y_disk)
        t_disk = np.arctan2(y_disk, x_disk)
        return x_disk, y_disk, r_disk, t_disk

    # -- Spectral Axis Manipulation -- #

    def velocity_to_restframe_frequency(self, velax=None, vlsr=0.0):
        """Return restframe frequency [Hz] of the given velocity [m/s]."""
        velax = self.velax if velax is None else np.squeeze(velax)
        return self.nu0 * (1. - (velax - vlsr) / 2.998e8)

    def restframe_frequency_to_velocity(self, nu, vlsr=0.0):
        """Return velocity [m/s] of the given restframe frequency [Hz]."""
        return 2.998e8 * (1. - nu / self.nu0) + vlsr

    def spectral_resolution(self, dV=None):
        """Convert velocity resolution in [m/s] to [Hz]."""
        dV = dV if dV is not None else self.chan
        nu = self.velocity_to_restframe_frequency(velax=[-dV, 0.0, dV])
        return np.mean([abs(nu[1] - nu[0]), abs(nu[2] - nu[1])])

    def velocity_resolution(self, dnu):
        """Convert spectral resolution in [Hz] to [m/s]."""
        v0 = self.restframe_frequency_to_velocity(self.nu0)
        v1 = self.restframe_frequency_to_velocity(self.nu0 + dnu)
        vA = max(v0, v1) - min(v0, v1)
        v1 = self.restframe_frequency_to_velocity(self.nu0 - dnu)
        vB = max(v0, v1) - min(v0, v1)
        return np.mean([vA, vB])

    # -- FITS I/O -- #

    def _read_FITS(self, path):
        """Reads the data from the FITS file."""

        # File names.
        self.path = os.path.expanduser(path)
        self.fname = self.path.split('/')[-1]

        # FITS data.
        self.header = fits.getheader(path)
        self.data = np.squeeze(fits.getdata(self.path))
        self.data = np.where(np.isfinite(self.data), self.data, 0.0)
        self.bunit = self.header['bunit']

        # Position axes.
        self.xaxis = self._readpositionaxis(a=1)
        self.yaxis = self._readpositionaxis(a=2)
        self.nxpix = self.xaxis.size
        self.nypix = self.yaxis.size
        self.dpix = np.mean([abs(np.diff(self.xaxis))])

        # Spectral axis.
        self.nu0 = self._readrestfreq()
        try:
            self.velax = self._readvelocityaxis()
            if self.velax.size > 1:
                self.chan = np.mean(np.diff(self.velax))
            else:
                self.chan = np.nan
            self.freqax = self._readfrequencyaxis()
            if self.chan < 0.0:
                self.data = self.data[::-1]
                self.velax = self.velax[::-1]
                self.freqax = self.freqax[::-1]
                self.chan *= -1.0
        except KeyError:
            self.velax = None
            self.chan = None
            self.freqax = None

        # Beam.
        self._read_beam()

    def _read_beam(self):
        """Reads the beam properties from the header."""
        try:
            if self.header.get('CASAMBM', False):
                beam = fits.open(self.path)[1].data
                beam = np.median([b[:3] for b in beam.view()], axis=0)
                self.bmaj, self.bmin, self.bpa = beam
            else:
                self.bmaj = self.header['bmaj'] * 3600.
                self.bmin = self.header['bmin'] * 3600.
                self.bpa = self.header['bpa']
            self.beamarea_arcsec = self._calculate_beam_area_arcsec()
            self.beamarea_str = self._calculate_beam_area_str()
        except Exception:
            print("WARNING: No beam values found. Assuming Jy/pix units.")
            self.bmaj = self.dpix
            self.bmin = self.dpix
            self.bpa = 0.0
            self.beamarea_arcsec = self.dpix**2.0
            self.beamarea_str = np.radians(self.dpix / 3600.)**2.0

    @property
    def beam(self):
        return self.bmaj, self.bmin, self.bpa

    @property
    def beam_per_pix(self):
        """Number of beams per pixel."""
        return self.dpix**2.0 / self.beamarea_arcsec

    @property
    def pix_per_beam(self):
        """Number of pixels in a beam."""
        return self.beamarea_arcsec / self.dpix**2.0

    def _clip_cube_velocity(self, v_min=None, v_max=None):
        """Clip the cube to within ``vmin`` and ``vmax``."""
        v_min = self.velax[0] if v_min is None else v_min
        v_max = self.velax[-1] if v_max is None else v_max
        i = abs(self.velax - v_min).argmin()
        i += 1 if self.velax[i] < v_min else 0
        j = abs(self.velax - v_max).argmin()
        j -= 1 if self.velax[j] > v_max else 0
        self.velax = self.velax[i:j+1]
        self.data = self.data[i:j+1]

    def _clip_cube_spatial(self, radius):
        """Clip the cube plus or minus clip arcseconds from the origin."""
        xa = abs(self.xaxis - radius).argmin()
        if self.xaxis[xa] < radius:
            xa -= 1
        xb = abs(self.xaxis + radius).argmin()
        if -self.xaxis[xb] < radius:
            xb += 1
        xb += 1
        ya = abs(self.yaxis + radius).argmin()
        if -self.yaxis[ya] < radius:
            ya -= 1
        yb = abs(self.yaxis - radius).argmin()
        if self.yaxis[yb] < radius:
            yb += 1
        yb += 1
        if self.data.ndim == 3:
            self.data = self.data[:, ya:yb, xa:xb]
        else:
            self.data = self.data[ya:yb, xa:xb]
        self.xaxis = self.xaxis[xa:xb]
        self.yaxis = self.yaxis[ya:yb]
        self.nxpix = self.xaxis.size
        self.nypix = self.yaxis.size

    def _readspectralaxis(self, a):
        """Returns the spectral axis in [Hz] or [m/s]."""
        a_len = self.header['naxis%d' % a]
        a_del = self.header['cdelt%d' % a]
        a_pix = self.header['crpix%d' % a]
        a_ref = self.header['crval%d' % a]
        return a_ref + (np.arange(a_len) - a_pix + 1.0) * a_del

    def _readpositionaxis(self, a=1):
        """Returns the position axis in [arcseconds]."""
        if a not in [1, 2]:
            raise ValueError("'a' must be in [0, 1].")
        a_len = self.header['naxis%d' % a]
        a_del = self.header['cdelt%d' % a]
        a_pix = self.header['crpix%d' % a] - 0.5
        axis = (np.arange(a_len) - a_pix + 1.0) * a_del
        return 3600 * axis

    def _readrestfreq(self):
        """Read the rest frequency."""
        try:
            nu = self.header['restfreq']
        except KeyError:
            try:
                nu = self.header['restfrq']
            except KeyError:
                try:
                    nu = self.header['crval3']
                except KeyError:
                    nu = np.nan
        return nu

    def _readvelocityaxis(self):
        """Wrapper for _velocityaxis and _spectralaxis."""
        a = 4 if 'stokes' in self.header['ctype3'].lower() else 3
        if 'freq' in self.header['ctype%d' % a].lower():
            specax = self._readspectralaxis(a)
            velax = (self.nu0 - specax) * sc.c
            velax /= self.nu0
        else:
            velax = self._readspectralaxis(a)
        return velax

    def _readfrequencyaxis(self):
        """Returns the frequency axis in [Hz]."""
        a = 4 if 'stokes' in self.header['ctype3'].lower() else 3
        if 'freq' in self.header['ctype3'].lower():
            return self._readspectralaxis(a)
        return self._readrestfreq() * (1.0 - self._readvelocityaxis() / sc.c)

    def frequency(self, vlsr=0.0, unit='GHz'):
        """
        A `velocity_to_restframe_frequency` wrapper with unit conversion.

        Args:
            vlsr (optional[float]): Sytemic velocity in [m/s].
            unit (optional[str]): Unit for the output axis.

        Returns:
            1D array of frequency values.
        """
        return self.frequency_offset(nu0=0.0, vlsr=vlsr, unit=unit)

    def frequency_offset(self, nu0=None, vlsr=0.0, unit='MHz'):
        """
        Return the frequency offset relative to `nu0` for easier plotting.

        Args:
            nu0 (optional[float]): Reference restframe frequency in [Hz].
            vlsr (optional[float]): Sytemic velocity in [m/s].
            unit (optional[str]): Unit for the output axis.

        Returns:
            1D array of frequency values.
        """
        nu0 = self.nu0 if nu0 is None else nu0
        nu = self.velocity_to_restframe_frequency(vlsr=vlsr)
        return (nu - nu0) / imagecube.frequency_units[unit]

    # -- Unit Conversions -- #

    def jybeam_to_Tb_RJ(self, data=None, nu=None):
        """[Jy/beam] to [K] conversion using Rayleigh-Jeans approximation."""
        nu = self.nu0 if nu is None else nu
        data = self.data if data is None else data
        jy2k = 1e-26 * sc.c**2 / nu**2 / 2. / sc.k
        return jy2k * data / self._calculate_beam_area_str()

    def jybeam_to_Tb(self, data=None, nu=None):
        """[Jy/beam] to [K] conversion using the full Planck law."""
        nu = self.nu0 if nu is None else nu
        data = self.data if data is None else data
        Tb = 1e-26 * abs(data) / self._calculate_beam_area_str()
        Tb = 2.0 * sc.h * nu**3 / Tb / sc.c**2
        Tb = sc.h * nu / sc.k / np.log(Tb + 1.0)
        return np.where(data >= 0.0, Tb, -Tb)

    def Tb_to_jybeam_RJ(self, data=None, nu=None):
        """[K] to [Jy/beam] conversion using Rayleigh-Jeans approxmation."""
        nu = self.nu0 if nu is None else nu
        data = self.data if data is None else data
        jy2k = 1e-26 * sc.c**2 / nu**2 / 2. / sc.k
        return data * self._calculate_beam_area_str() / jy2k

    def Tb_to_jybeam(self, data=None, nu=None):
        """[K] to [Jy/beam] conversion using the full Planck law."""
        nu = self.nu0 if nu is None else nu
        data = self.data if data is None else data
        Fnu = 2. * sc.h * nu**3 / sc.c**2
        Fnu /= np.exp(sc.h * nu / sc.k / abs(data)) - 1.0
        Fnu *= self._calculate_beam_area_str() / 1e-26
        return np.where(data >= 0.0, Fnu, -Fnu)

    def _calculate_beam_area_arcsec(self):
        """Beam area in square arcseconds."""
        omega = self.bmin * self.bmaj
        if self.bmin == self.dpix and self.bmaj == self.dpix:
            return omega
        return np.pi * omega / 4. / np.log(2.)

    def _calculate_beam_area_str(self):
        """Beam area in steradians."""
        omega = np.radians(self.bmin / 3600.)
        omega *= np.radians(self.bmaj / 3600.)
        if self.bmin == self.dpix and self.bmaj == self.dpix:
            return omega
        return np.pi * omega / 4. / np.log(2.)

    # -- Utilities -- #

    def estimate_RMS(self, N=5):
        """Estimate RMS of the cube based on first and last `N` channels."""
        rms = np.concatenate([self.data[:int(N)], self.data[-int(N):]])
        return np.sqrt(np.sum(rms**2) / rms.size)

    def correct_PB(self, path):
        """Correct for the primary beam given by ``path``."""
        if self._pb_corrected:
            raise ValueError("This data has already been PB corrected.")
        pb = np.squeeze(fits.getdata(path))
        if pb.shape == self.data.shape:
            self.data /= pb
        else:
            self.data /= pb[None, :, :]
        self._pb_corrected = True

    @property
    def rms(self):
        """RMS of the cube based on the first and last 5 channels."""
        return self.estimate_RMS(N=5)

    @property
    def extent(self):
        """Cube field of view for use with Matplotlib's ``imshow``."""
        return [self.xaxis[0], self.xaxis[-1], self.yaxis[0], self.yaxis[-1]]

    # -- Spiral Functions -- #

    def spiral_coords(self, r_p, t_p, m=None, r_min=None, r_max=None,
                      mstar=1.0, T0=20.0, Tq=-0.5, dist=100., clockwise=True,
                      frame_out='cartesian'):
        """
        Spiral coordinates from Bae & Zhaohuan (2018a). In order to recover the
        linear spirals from Rafikov (2002), use m >> 1.
        Args:
            r_p (float): Orbital radius of the planet in [arcsec].
            t_p (float): Polar angle of planet relative to the red-shifted
                major axis of the disk in [radians].
            m (optional[int]): Azimuthal wavenumber of the spiral. If not
                specified, will assume the dominant term based on the rotation
                and temperature profiles.
            r_min (optional[float]): Inner radius of the spiral in [arcsec].
            r_max (optional[float]): Outer radius of the spiral in [arcsec].
            mstar (optioanl[float]): Stellar mass of the central star in [Msun]
                to calculate the rotation profile.
            T0 (optional[float]): Gas temperature in [K] at 1 arcsec.
            Tq (optional[float]): Exoponent of the radial gas temperature
                profile.
            dist (optional[float]): Source distance in [pc] used to scale
                [arcsec] to [au] in the calculation of the rotation profile.
            clockwise (optional[bool]): Direction of the spiral.
            frame_out (optional[str]): Coordinate frame of the returned values,
                either 'cartesian' or 'cylindrical'.
        Returns:
            ndarray:
                Coordinates of the spiral in either cartestian or cylindrical
                frame.
        """

        # Define the radial grid in [arcsec].
        r_min = 0.1 if r_min is None else r_min
        r_max = self.xaxis.max() if r_max is None else r_max
        rvals = np.arange(r_min, r_max, 0.1 * self.dpix)
        clockwise = -1.0 if clockwise is True else 1.0

        # Define the physical properties as a function of radius. SI units.
        omega = np.sqrt(sc.G * mstar * 1.988e30 * (rvals * sc.au * dist)**-3)
        tgas = T0 * np.power(rvals, Tq)
        cs = np.sqrt(sc.k * tgas / 2.37 / sc.m_p)
        H = cs / omega

        # Define the dominant wave number if not defined.
        if m is None:
            m = 0.5 * (r_p * dist * sc.au / H)[abs(rvals - r_p).argmin()]
        m = np.round(m)
        rmn = r_p * dist * sc.au * (1.0 - 1.0 / m)**(2./3.)
        rmp = r_p * dist * sc.au * (1.0 + 1.0 / m)**(2./3.)

        # Integrate the equation numerically.
        x = rvals * dist * sc.au
        y = omega * np.sqrt(abs((1 - (rvals / r_p)**(3./2.))**2 - m**-2.)) / cs
        idx_n = abs(rvals * sc.au * dist - rmn).argmin()
        idx_p = abs(rvals * sc.au * dist - rmp).argmin()
        phi = np.ones(rvals.size) * t_p

        for i, r in enumerate(x):
            phi[i] = t_p - np.sign(r - r_p) * np.pi / 4. / m
            if r <= rmn:
                phi[i] -= clockwise * np.trapz(y[i:idx_n+1][::-1],
                                               x=x[i:idx_n+1][::-1])
            elif r >= rmp:
                phi[i] -= clockwise * np.trapz(y[idx_p:i+1],
                                               x=x[idx_p:i+1])
            else:
                phi[i] = np.nan

        # Return the spirals.
        if frame_out == 'cylindrical':
            return rvals, phi
        return rvals * np.cos(phi), rvals * np.sin(phi)

    def disk_to_sky(self, coords, x0=0.0, y0=0.0, inc=0.0, PA=0.0, z0=0.0,
                    psi=1.0, z1=0.0, phi=0.0, z_func=None, return_idx=False,
                    frame_in='cylindrical', shadowed=True):
        """
        For a given disk midplane coordinate, either (r, theta) or (x, y),
        return interpolated sky coordiantes in (x, y) for plotting. The input
        needs to be a list like: ``coords = (rvals, tvals)``.

        Args:
            coords (list): Midplane coordaintes to find in (x, y) in [arcsec,
                arcsec] or (r, theta) in [arcsec, deg].
            x0 (Optional[float]): Source right ascension offset [arcsec].
            y0 (Optional[float]): Source declination offset [arcsec].
            inc (Optional[float]): Source inclination [deg].
            PA (Optional[float]): Source position angle [deg]. Measured
                between north and the red-shifted semi-major axis in an
                easterly direction.
            z0 (Optional[float]): Aspect ratio at 1" for the emission surface.
                To get the far side of the disk, make this number negative.
            psi (Optional[float]): Flaring angle for the emission surface.
            z1 (Optional[float]): Aspect ratio correction term at 1" for the
                emission surface. Should be opposite sign to ``z0``.
            phi (Optional[float]): Flaring angle correction term for the
                emission surface.
            z_func (Optional[callable]): User-defined function returning z in
                [arcsec] at a given radius in [arcsec].
            return_idx (Optional[bool]): If True, return the indices of the
                nearest pixels rather than the interpolated values.
            frame (Optional[str]): Frame of input coordinates, either
                'cartesian' or 'polar'.

        Returns:
            x (float/int): Either the sky plane x-coordinate in [arcsec] or the
                index of the closest pixel.
            y (float/int): Either the sky plane y-coordinate in [arcsec] or the
                index of the closest pixel.
        """

        # Import the necessary module.

        try:
            from scipy.interpolate import griddata
        except Exception:
            raise ValueError("Can't find 'scipy.interpolate.griddata'.")

        # Make sure input coords are cartesian.

        frame_in = frame_in.lower()
        if frame_in not in ['cylindrical', 'cartesian']:
            raise ValueError("frame_in must be 'cylindrical' or 'cartesian'.")
        if frame_in == 'cylindrical':
            xdisk = coords[0] * np.cos(np.radians(coords[1]))
            ydisk = coords[0] * np.sin(np.radians(coords[1]))
        else:
            xdisk, ydisk = coords
        xdisk, ydisk = np.squeeze(xdisk), np.squeeze(ydisk)

        # Grab disk coordinates and sky coordinates to interpolate between.

        xdisk_grid, ydisk_grid = self.disk_coords(x0=x0, y0=y0, inc=inc, PA=PA,
                                                  z0=z0, psi=psi, z1=z1,
                                                  phi=phi, z_func=z_func,
                                                  frame='cartesian',
                                                  shadowed=shadowed)[:2]
        xdisk_grid, ydisk_grid = xdisk_grid.flatten(), ydisk_grid.flatten()
        xsky_grid, ysky_grid = self._get_cart_sky_coords(x0=x0, y0=y0)
        xsky_grid, ysky_grid = xsky_grid.flatten(), ysky_grid.flatten()

        xsky = griddata((xdisk_grid, ydisk_grid), xsky_grid, (xdisk, ydisk),
                        method='nearest' if return_idx else 'linear',
                        fill_value=np.nan)
        ysky = griddata((xdisk_grid, ydisk_grid), ysky_grid, (xdisk, ydisk),
                        method='nearest' if return_idx else 'linear',
                        fill_value=np.nan)
        xsky, ysky = np.squeeze(xsky), np.squeeze(ysky)

        # Return the values or calculate the indices.

        if not return_idx:
            xsky = xsky if xsky.size > 1 else xsky[0]
            ysky = ysky if ysky.size > 1 else ysky[0]
            return xsky, ysky
        xidx = np.array([abs(self.xaxis - x).argmin() for x in xsky])
        yidx = np.array([abs(self.yaxis - y).argmin() for y in ysky])
        xidx = xidx if xidx.size > 1 else xidx[0]
        yidx = yidx if yidx.size > 1 else yidx[0]
        return xidx, yidx

    # -- Plotting Functions -- #

    def plot_center(self, x0s, y0s, SNR, normalize=True):
        """Plot the array of SNR values."""
        import matplotlib.pyplot as plt

        # Find the center.
        SNR_mask = np.isfinite(SNR)
        SNR = np.where(SNR_mask, SNR, -1e10)
        yidx, xidx = np.unravel_index(SNR.argmax(), SNR.shape)
        SNR = np.where(SNR_mask, SNR, np.nan)
        x0, y0 = x0s[xidx], y0s[yidx]
        print('Peak SNR at (x0, y0) = ({:.2f}", {:.2f}").'.format(x0, y0))

        # Define the levels.
        if normalize:
            SNR /= SNR[abs(y0s).argmin(), abs(x0s).argmin()]
            vmax = abs(SNR - 1.0).max()
            vmin = 1.0 - vmax
            vmax = 1.0 + vmax
            cb_label = 'Normalized SNR'
        else:
            vmax = SNR.min()
            vmin = SNR.max()
            cb_label = 'SNR'

        # Plot the figure.
        _, ax = plt.subplots()
        im = ax.imshow(SNR, extent=[x0s[0], x0s[-1], y0s[0], y0s[-1]],
                       origin='lower', vmax=vmax, vmin=vmin, cmap='RdGy_r')
        cb = plt.colorbar(im, pad=0.02)
        cb.set_label(cb_label, rotation=270, labelpad=13)
        ax.scatter(x0, y0, marker='x', s=60, c='w', linewidths=2.)
        ax.scatter(x0, y0, marker='x', s=30, c='k', linewidths=1.)
        ax.set_aspect(1)
        ax.set_xlim(x0s[-1], x0s[0])
        ax.set_ylim(y0s[0], y0s[-1])
        ax.set_xlabel('Offset (arcsec)')
        ax.set_ylabel('Offset (arcsec)')
        self._plot_beam(ax=ax)

    def plot_teardrop(self, inc, PA, mstar, dist, ax=None, rvals=None,
                      rbins=None, dr=None, x0=0.0, y0=0.0, z0=0.0, psi=1.0,
                      z1=0.0, phi=0.0, z_func=None, resample=1,
                      beam_spacing=False, r_min=None, r_max=None,
                      PA_min=None, PA_max=None, exclude_PA=False, abs_PA=False,
                      mask_frame='disk', unit='Jy/beam', imshow_kwargs=None,
                      shadowed=True):
        """
        Make a `teardrop` plot. For argument descriptions see
        ``radial_spectra``. For all properties related to ``imshow``, include
        them in ``imshow_kwargs`` as a dictionary, e.g.

            imshow_kwargs = dict(cmap='inferno', vmin=0.0, vmax=1.0)

        This will override any of the default style parameters.
        """
        # Imports
        import matplotlib.pyplot as plt

        # Grab the spectra.
        out = self.radial_spectra(rbins=rbins, rvals=rvals, dr=dr, x0=x0,
                                  y0=y0, inc=inc, PA=PA, z0=z0, psi=psi, z1=z1,
                                  phi=phi, z_func=z_func, mstar=mstar,
                                  dist=dist, resample=resample,
                                  beam_spacing=beam_spacing, r_min=r_min,
                                  r_max=r_max, PA_min=PA_min, PA_max=PA_max,
                                  exclude_PA=exclude_PA, abs_PA=abs_PA,
                                  mask_frame=mask_frame, unit=unit,
                                  shadowed=shadowed)
        rvals, spectra = out
        velax = spectra[0, 0]

        # Generate the axes.
        if ax is None:
            fig, ax = plt.subplots()

        # Plot the figure.
        extent = [velax[0], velax[-1], rvals[0], rvals[-1]]
        imshow_kwargs = {} if imshow_kwargs is None else imshow_kwargs
        imshow_kwargs['origin'] = imshow_kwargs.pop('origin', 'lower')
        imshow_kwargs['cmap'] = imshow_kwargs.pop('cmap', 'inferno')
        imshow_kwargs['aspect'] = imshow_kwargs.pop('aspect', 'auto')
        imshow_kwargs['extent'] = imshow_kwargs.pop('extent', extent)
        im = ax.imshow(spectra[:, 1], **imshow_kwargs)
        cb = plt.colorbar(im, pad=0.02)
        cb.set_label('({})'.format(unit), rotation=270, labelpad=13)
        ax.set_xlabel('Velocity (m/s)')
        ax.set_ylabel('Radius (arcsec)')
        return ax

    def plot_beam(self, ax, x0=0.1, y0=0.1, **kwargs):
        """
        Plot the sythensized beam on the provided axes.

        Args:
            ax (matplotlib axes instance): Axes to plot the FWHM.
            x0 (float): Relative x-location of the marker.
            y0 (float): Relative y-location of the marker.
            kwargs (dic): Additional kwargs for the style of the plotting.
        """
        from matplotlib.patches import Ellipse
        beam = Ellipse(ax.transLimits.inverted().transform((x0, y0)),
                       width=self.bmin, height=self.bmaj, angle=-self.bpa,
                       fill=False, hatch=kwargs.pop('hatch', '////////'),
                       lw=kwargs.pop('linewidth', kwargs.pop('lw', 1)),
                       color=kwargs.pop('color', kwargs.pop('c', 'k')),
                       zorder=kwargs.pop('zorder', 1000), **kwargs)
        ax.add_patch(beam)

    def plot_mask(self, ax, r_min=None, r_max=None, exclude_r=False,
                  PA_min=None, PA_max=None, exclude_PA=False, abs_PA=False,
                  mask_frame='disk', mask=None, x0=0.0, y0=0.0, inc=0.0,
                  PA=0.0, z0=0.0, psi=1.0, z1=0.0, phi=1.0, z_func=None,
                  mask_color='k', mask_alpha=0.5, contour_kwargs=None,
                  contourf_kwargs=None, shadowed=True):
        """
        Plot the boolean mask on the provided axis to check that it makes
        sense.

        Args:
            ax (matplotib axis instance): Axis to plot the mask.
            r_min (Optional[float]): Minimum midplane radius of the annulus in
                [arcsec]. Defaults to minimum deprojected radius.
            r_max (Optional[float]): Maximum midplane radius of the annulus in
                [arcsec]. Defaults to the maximum deprojected radius.
            exclude_r (Optional[bool]): If ``True``, exclude the provided
                radial range rather than include.
            PA_min (Optional[float]): Minimum polar angle of the segment of the
                annulus in [degrees]. Note this is the polar angle, not the
                position angle.
            PA_max (Optional[float]): Maximum polar angle of the segment of the
                annulus in [degrees]. Note this is the polar angle, not the
                position angle.
            exclude_PA (Optional[bool]): If ``True``, exclude the provided
                polar angle range rather than include it.
            abs_PA (Optional[bool]): If ``True``, take the absolute value of
                the polar angle such that it runs from 0 [deg] to 180 [deg].
            x0 (Optional[float]): Source center offset along the x-axis in
                [arcsec].
            y0 (Optional[float]): Source center offset along the y-axis in
                [arcsec].
            inc (Optional[float]): Inclination of the disk in [degrees].
            PA (Optional[float]): Position angle of the disk in [degrees],
                measured east-of-north towards the redshifted major axis.
            z0 (Optional[float]): Emission height in [arcsec] at a radius of
                1".
            psi (Optional[float]): Flaring angle of the emission surface.
            z1 (Optional[float]): Correction to emission height at 1" in
                [arcsec].
            phi (Optional[float]): Flaring angle correction term.
            z_func (Optional[function]): A function which provides
                :math:`z(r)`. Note that no checking will occur to make sure
                this is a valid function.
            mask_color (Optional[str]): Color used for the mask lines.
            mask_alpha (Optional[float]): The alpha value of the filled contour
                of the masked regions. Setting ``mask_alpha=0.0`` will remove
                the filling.

            contour_kwargs (Optional[dict]): Kwargs to pass to contour for
                drawing the mask.

        Returns:
            ax : The matplotlib axis instance.
        """
        # Grab the mask.
        if mask is None:
            mask = self.get_mask(r_min=r_min, r_max=r_max, exclude_r=exclude_r,
                                 PA_min=PA_min, PA_max=PA_max,
                                 exclude_PA=exclude_PA, abs_PA=abs_PA,
                                 mask_frame=mask_frame, x0=x0, y0=y0, inc=inc,
                                 PA=PA, z0=z0, psi=psi, z1=z1, phi=phi,
                                 z_func=z_func, shadowed=shadowed)
        assert mask.shape[0] == self.yaxis.size, "Wrong y-axis shape for mask."
        assert mask.shape[1] == self.xaxis.size, "Wrong x-axis shape for mask."

        # Set the default plotting style.
        contour_kwargs = {} if contour_kwargs is None else contour_kwargs
        contour_kwargs['colors'] = contour_kwargs.pop('colors', mask_color)
        contour_kwargs['linewidths'] = contour_kwargs.pop('linewidths', 1.0)
        contour_kwargs['linestyles'] = contour_kwargs.pop('linestyles', '-')
        contourf_kwargs = {} if contourf_kwargs is None else contourf_kwargs
        contourf_kwargs['alpha'] = contourf_kwargs.pop('alpha', mask_alpha)
        contourf_kwargs['colors'] = contourf_kwargs.pop('colors', mask_color)

        # Plot the contour and return the figure.
        ax.contourf(self.xaxis, self.yaxis, mask, [-.5, .5], **contourf_kwargs)
        ax.contour(self.xaxis, self.yaxis, mask, 1, **contour_kwargs)
