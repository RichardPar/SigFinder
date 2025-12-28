#!/usr/bin/env python3
"""sigfinder.main

Opens a GPS serial port and configures an ADALM‑Pluto LO frequency.
"""
import argparse
import threading
import time
import sys
from typing import Optional
import math
import os
import json

try:
    import serial
except Exception:  # pragma: no cover - runtime import
    serial = None

try:
    import adi
except Exception:  # pragma: no cover - runtime import
    adi = None

try:
    import SoapySDR
except Exception:  # pragma: no cover - runtime import
    SoapySDR = None


current_position: dict = {"lat": None, "lon": None}
gui_log: list = []
gui_log_lock = threading.Lock()
current_status = {"fix_quality": 0, "num_sats": 0, "rmc_status": "V", "last_time": None}
current_status = {"fix_quality": 0, "num_sats": 0, "rmc_status": "V", "last_time": None, "fix_count": 0}
current_status.setdefault('rssi_max', None)
DEBUG = False
RSSI_OFFSET = 0.0  # dB offset to convert measured RSSI to approximate dBm
# Signal logging configuration (can be set by CLI)
SIGNAL_LOG_FILE: str | None = None
SIGNAL_MIN_DB = -120.0  # display dBm threshold (negative values); samples >= this are considered signals
# Config file path for persisting UI settings (range trigger) and last known position
CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.config', 'sigfinder')
CONFIG_PATH = os.path.join(CONFIG_DIR, 'config.json')
# Thread-safe queue for signal events to be consumed by GUI updater
signal_event_lock = threading.Lock()
signal_event_queue: list = []


def _nmea_to_decimal(coord: str, hemi: str) -> Optional[float]:
    # coord is ddmm.mmmm or dddmm.mmmm
    if not coord:
        return None
    try:
        dot = coord.find('.')
        if dot == -1:
            return None
        degrees_len = dot - 2
        degrees = float(coord[:degrees_len])
        minutes = float(coord[degrees_len:])
        dec = degrees + minutes / 60.0
        if hemi in ('S', 'W'):
            dec = -dec
        return dec
    except Exception:
        return None


def gps_reader(port: str, baud: int, stop_event: threading.Event):
    if serial is None:
        print("pyserial is not installed. Install dependencies and retry.")
        return
    try:
        ser = serial.Serial(port, baud, timeout=1)
    except Exception as e:
        print(f"Failed to open GPS serial port {port}: {e}")
        return
    print(f"GPS: opened {port} @ {baud}")
    try:
        while not stop_event.is_set():
            try:
                line = ser.readline()
            except Exception as e:
                print(f"GPS read error: {e}")
                break
            if not line:
                continue
            try:
                text = line.decode("ascii", errors="ignore").strip()
            except Exception:
                text = repr(line)

            if text:
                # Only print/store raw NMEA when DEBUG enabled (raw NMEA is noisy)
                if DEBUG:
                    print(f"[GPS] {text}")
                    # store NMEA sentence in GUI log buffer
                    try:
                        with gui_log_lock:
                            gui_log.append(text)
                            # keep log reasonably bounded
                            if len(gui_log) > 500:
                                gui_log[:] = gui_log[-500:]
                    except Exception:
                        pass

                # Try to parse common NMEA sentences for position
                # GPGGA: lat (ddmm.mmmm), N/S, lon (dddmm.mmmm), E/W
                try:
                        # remove checksum part if present
                        core = text.split('*', 1)[0]
                        parts = core.split(',')
                        if not parts:
                            continue
                        talker = parts[0].lstrip('$')
                        typ = talker[-3:]

                        if typ == 'GGA' and len(parts) > 5:
                            # GGA: _,time,lat,NS,lon,EW,...
                            if DEBUG:
                                print(f"GGA raw parts: {parts}")
                            lat = _nmea_to_decimal(parts[2], parts[3])
                            lon = _nmea_to_decimal(parts[4], parts[5])
                            if lat is not None and lon is not None:
                                current_position['lat'] = lat
                                current_position['lon'] = lon
                                # parsed fix messages are noisy; only emit in DEBUG
                                if DEBUG:
                                    print(f"Parsed GPS GGA fix: {lat:.6f}, {lon:.6f}")
                                current_status['fix_count'] += 1
                            # update status fields (fix quality, satellites)
                            try:
                                fq = int(parts[6]) if parts[6] else 0
                            except Exception:
                                fq = 0
                            try:
                                ns = int(parts[7]) if parts[7] else 0
                            except Exception:
                                ns = 0
                            current_status['fix_quality'] = fq
                            current_status['num_sats'] = ns
                            current_status['last_time'] = parts[1] if len(parts) > 1 else current_status.get('last_time')

                        if typ == 'RMC' and len(parts) > 6:
                            # RMC: _,time,status,lat,NS,lon,EW, ...
                            if DEBUG:
                                print(f"RMC raw parts: {parts}")
                            try:
                                lat = _nmea_to_decimal(parts[3], parts[4])
                                lon = _nmea_to_decimal(parts[5], parts[6])
                                if lat is not None and lon is not None:
                                    current_position['lat'] = lat
                                    current_position['lon'] = lon
                                    if DEBUG:
                                        print(f"Parsed GPS RMC fix: {lat:.6f}, {lon:.6f}")
                                    current_status['fix_count'] += 1
                                    # RMC status typically in parts[2]
                                try:
                                    rmc = parts[2] if len(parts) > 2 else current_status.get('rmc_status')
                                except Exception:
                                    rmc = current_status.get('rmc_status')
                                current_status['rmc_status'] = rmc
                            except Exception:
                                pass
                        # GSV reports satellites in view: parts[3] is total satellites
                        if typ == 'GSV' and len(parts) > 3:
                            try:
                                total_sats = int(parts[3]) if parts[3] else 0
                                prev = current_status.get('num_sats', 0)
                                current_status['num_sats'] = total_sats
                                if total_sats != prev:
                                    if DEBUG:
                                        print(f"GSV total satellites reported: {total_sats}")
                            except Exception:
                                pass
                except Exception:
                    # ignore parse errors
                    pass
    finally:
        try:
            ser.close()
        except Exception:
            pass


def configure_pluto(uri: str | None, freq_hz: int, rx_bw_hz: int = 125000):
    if adi is None:
        print("pyadi-iio (adi) not installed. Install dependencies and retry.")
        return None
    try:
        # If uri is empty string, pass None to let pyadi-iio try default
        dev = adi.Pluto(uri) if uri else adi.Pluto()
    except Exception as e:
        print(f"Failed to open ADALM-Pluto device: {e}")
        return None

    try:
        # Set RX and TX LO to desired frequency (Hz). Some devices require setting both.
        dev.rx_lo = int(freq_hz)
        dev.tx_lo = int(freq_hz)
        print(f"Pluto: set RX/TX LO to {freq_hz} Hz")
        # Try to set RX bandwidth to requested value (125 kHz default). Many drivers support this.
        try:
            dev.rx_rf_bandwidth = int(rx_bw_hz)
            # also set TX RF bandwidth if appropriate
            try:
                dev.tx_rf_bandwidth = int(rx_bw_hz)
            except Exception:
                pass
            # Ensure sample rate is reasonable for this bandwidth. AD936x device may impose a minimum.
            # Choose at least 1 MHz (device implementation enforces ~521 kHz lower bound).
            desired_sr = max(1000000, int(rx_bw_hz * 8))
            try:
                dev.sample_rate = int(desired_sr)
            except Exception:
                # ignore if device refuses sample rate
                pass
            print(f"Pluto: set RX BW to {rx_bw_hz} Hz, sample_rate approx {desired_sr} Hz")
        except Exception as e:
            print(f"Pluto: unable to set RX BW {rx_bw_hz} Hz: {e}")
    except Exception as e:
        print(f"Failed to set LO frequency: {e}")
        return dev

    return dev


def configure_sdrplay(freq_hz: int, rx_bw_hz: int = 125000, gain: float = 40.0):
    """Configure SDRplay device using SoapySDR.
    
    Args:
        freq_hz: Center frequency in Hz
        rx_bw_hz: Receiver bandwidth in Hz
        gain: RF gain in dB (default 40.0)
    
    Returns:
        SoapySDR device object or None on failure
    """
    if SoapySDR is None:
        print("SoapySDR not installed. Install SoapySDR Python bindings and retry.")
        return None
    
    try:
        # Find SDRplay devices
        results = SoapySDR.Device.enumerate("driver=sdrplay")
        if not results:
            print("No SDRplay devices found")
            return None
        
        print(f"Found SDRplay device: {results[0]}")
        
        # Open first SDRplay device
        dev = SoapySDR.Device(results[0])
        
        # Configure RX channel 0
        channel = 0
        
        # Set frequency
        dev.setFrequency(SoapySDR.SOAPY_SDR_RX, channel, float(freq_hz))
        print(f"SDRplay: set frequency to {freq_hz} Hz")
        
        # Set sample rate (at least 1 MHz or 8x bandwidth)
        sample_rate = max(1000000, int(rx_bw_hz * 8))
        dev.setSampleRate(SoapySDR.SOAPY_SDR_RX, channel, float(sample_rate))
        print(f"SDRplay: set sample rate to {sample_rate} Hz")
        
        # Set bandwidth
        dev.setBandwidth(SoapySDR.SOAPY_SDR_RX, channel, float(rx_bw_hz))
        print(f"SDRplay: set bandwidth to {rx_bw_hz} Hz")
        
        # Set gain
        dev.setGain(SoapySDR.SOAPY_SDR_RX, channel, float(gain))
        print(f"SDRplay: set gain to {gain} dB")
        
        # Setup RX stream
        dev._rx_stream = dev.setupStream(SoapySDR.SOAPY_SDR_RX, SoapySDR.SOAPY_SDR_CF32, [channel])
        dev.activateStream(dev._rx_stream)
        print("SDRplay: RX stream activated")
        
        # Add metadata for device type
        dev._device_type = 'sdrplay'
        
        return dev
        
    except Exception as e:
        print(f"Failed to configure SDRplay device: {e}")
        return None


def configure_rtlsdr(freq_hz: int, rx_bw_hz: int = 125000, gain: float = 40.0):
    """Configure RTL-SDR device using SoapySDR.
    
    Args:
        freq_hz: Center frequency in Hz
        rx_bw_hz: Receiver bandwidth in Hz (used for sample rate calculation)
        gain: RF gain in dB (default 40.0, 'auto' sets automatic gain)
    
    Returns:
        SoapySDR device object or None on failure
    """
    # Prefer native pyrtlsdr (rtlsdr.RtlSdr) if available; fall back to SoapySDR
    try:
        from rtlsdr import RtlSdr
    except Exception:
        RtlSdr = None

    # Native pyrtlsdr backend
    if RtlSdr is not None:
        try:
            import numpy as _np

            class _RtlSdrWrapper:
                """Lightweight wrapper around pyrtlsdr.RtlSdr exposing a minimal
                readStream/deactivateStream/closeStream API used elsewhere in the
                code. This allows `_sample_rssi_from_device()` to treat the
                device similarly to SoapySDR devices.
                """
                def __init__(self):
                    self._s = RtlSdr()
                    # default sample rate: use 2 MHz for RTL-SDR
                    try:
                        self._s.sample_rate = 2e6
                    except Exception:
                        pass
                    self._device_type = 'rtlsdr'
                    # dummy stream token
                    self._rx_stream = object()

                # Provide convenience attributes expected by code
                def set_sample_rate(self, sr):
                    try:
                        self._s.sample_rate = float(sr)
                    except Exception:
                        pass

                def set_center_freq(self, freq_hz):
                    try:
                        self._s.center_freq = float(freq_hz)
                    except Exception:
                        try:
                            self._s.set_center_freq(int(freq_hz))
                        except Exception:
                            pass

                def set_gain(self, g):
                    try:
                        # if g <= 0 attempt AGC where available
                        if g <= 0:
                            try:
                                if hasattr(self._s, 'set_agc'):
                                    self._s.set_agc(True)
                                else:
                                    # some pyrtlsdr versions support 'gain = "auto"'
                                    try:
                                        self._s.gain = 'auto'
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                        else:
                            try:
                                self._s.gain = float(min(g, 50.0))
                            except Exception:
                                pass
                    except Exception:
                        pass

                # readStream signature: (stream, [buffer], length, timeoutUs=...)
                def readStream(self, stream, buffers, length, timeoutUs=500000):
                    # buffers is a list containing a numpy array to fill
                    try:
                        # pyrtlsdr.read_samples returns complex64 array
                        samples = self._s.read_samples(length)
                        if samples is None:
                            class _R:
                                ret = 0
                            return _R()
                        n = min(len(samples), length)
                        buf = buffers[0]
                        # ensure dtype complex64
                        if buf.dtype != _np.complex64:
                            try:
                                buf = buf.view(_np.complex64)
                            except Exception:
                                pass
                        buf[:n] = samples[:n]

                        class _R:
                            pass

                        r = _R()
                        r.ret = n
                        return r
                    except Exception:
                        class _R:
                            ret = 0
                        return _R()

                def activateStream(self, stream):
                    # no-op for pyrtlsdr wrapper
                    return

                def deactivateStream(self, stream):
                    return

                def closeStream(self, stream):
                    return

                def close(self):
                    try:
                        self._s.close()
                    except Exception:
                        pass

            dev = _RtlSdrWrapper()

            # Configure frequency, sample rate and gain
            try:
                dev.set_center_freq(freq_hz)
                print(f"RTL-SDR (native): set frequency to {freq_hz} Hz")
            except Exception:
                pass
            try:
                sr = 2000000
                dev.set_sample_rate(sr)
                print(f"RTL-SDR (native): set sample rate to {sr} Hz")
            except Exception:
                pass
            try:
                dev.set_gain(gain)
                print(f"RTL-SDR (native): set gain to {gain} dB (or AGC)")
            except Exception:
                pass

            # mark device
            dev._device_type = 'rtlsdr'
            print("RTL-SDR: native pyrtlsdr backend configured")
            return dev
        except Exception as e:
            print(f"RTL-SDR: native pyrtlsdr backend failed: {e}")

    # Fall back to SoapySDR if available
    if SoapySDR is None:
        print("SoapySDR not installed and pyrtlsdr not available. Install pyrtlsdr or SoapySDR and retry.")
        return None

    try:
        # Find RTL-SDR devices via Soapy
        results = SoapySDR.Device.enumerate("driver=rtlsdr")
        if not results:
            print("No RTL-SDR devices found")
            return None

        print(f"Found RTL-SDR device: {results[0]}")

        # Open first RTL-SDR device
        dev = SoapySDR.Device(results[0])

        # Configure RX channel 0
        channel = 0

        # Set frequency
        dev.setFrequency(SoapySDR.SOAPY_SDR_RX, channel, float(freq_hz))
        print(f"RTL-SDR: set frequency to {freq_hz} Hz")

        # Set sample rate (RTL-SDR supports up to 2.4 MHz typically)
        # Use 2 MHz as default for better performance
        sample_rate = 2000000
        dev.setSampleRate(SoapySDR.SOAPY_SDR_RX, channel, float(sample_rate))
        print(f"RTL-SDR: set sample rate to {sample_rate} Hz")

        # RTL-SDR doesn't have adjustable bandwidth filter, but we can set it anyway
        try:
            dev.setBandwidth(SoapySDR.SOAPY_SDR_RX, channel, float(rx_bw_hz))
            print(f"RTL-SDR: set bandwidth to {rx_bw_hz} Hz")
        except Exception:
            pass  # Some RTL-SDR drivers don't support setBandwidth

        # Set gain (RTL-SDR gain range is typically 0-50 dB)
        # If gain is 0 or negative, enable AGC
        if gain <= 0:
            try:
                dev.setGainMode(SoapySDR.SOAPY_SDR_RX, channel, True)  # Enable AGC
                print("RTL-SDR: enabled automatic gain control")
            except Exception:
                pass
        else:
            try:
                dev.setGainMode(SoapySDR.SOAPY_SDR_RX, channel, False)  # Disable AGC
                dev.setGain(SoapySDR.SOAPY_SDR_RX, channel, float(min(gain, 50.0)))
                print(f"RTL-SDR: set gain to {min(gain, 50.0)} dB")
            except Exception as e:
                print(f"RTL-SDR: could not set gain: {e}")

        # Setup RX stream
        dev._rx_stream = dev.setupStream(SoapySDR.SOAPY_SDR_RX, SoapySDR.SOAPY_SDR_CF32, [channel])
        dev.activateStream(dev._rx_stream)
        print("RTL-SDR: RX stream activated")

        # Add metadata for device type
        dev._device_type = 'rtlsdr'

        return dev

    except Exception as e:
        print(f"Failed to configure RTL-SDR device: {e}")
        return None


def _sample_rssi_from_device(dev):
    """Try several methods to obtain an RSSI-like metric from a pyadi-iio device or SoapySDR device.
    Returns a numeric value (dB-like) or None if not available.
    This is defensive: different pyadi drivers expose RSSI differently.
    """
    # Keep last valid value as fallback for dropped samples
    if not hasattr(_sample_rssi_from_device, 'last_valid'):
        _sample_rssi_from_device.last_valid = {}
    
    try:
        # Check if this is a SoapySDR device (SDRplay or RTL-SDR)
        if hasattr(dev, '_device_type') and dev._device_type in ('sdrplay', 'rtlsdr'):
            try:
                import numpy as _np
                # Read samples from SoapySDR stream
                # Use larger buffer and longer timeout to avoid dropped samples
                buffer = _np.zeros(8192, dtype=_np.complex64)
                sr = dev.readStream(dev._rx_stream, [buffer], len(buffer), timeoutUs=500000)
                if sr.ret > 0:
                    samples = buffer[:sr.ret]
                    # Compute power in dBFS
                    p = _np.mean(_np.abs(samples)**2)
                    if p <= 0:
                        # Return last valid value if available
                        return _sample_rssi_from_device.last_valid.get(id(dev))
                    dbfs = 10.0 * math.log10(float(p))
                    
                    # Convert dBFS to approximate dBm based on device type
                    # RTL-SDR calibration: RTL-SDR dongles typically have noise floor around -90 to -100 dBm
                    # Adjusted calibration: dBm ≈ dBFS - 80
                    # This gives: -20 dBFS → -100 dBm, -30 dBFS → -110 dBm
                    if dev._device_type == 'rtlsdr':
                        # RTL-SDR calibration: approximate dBm from dBFS
                        # Adjust offset to match typical RF power levels
                        dbm_estimate = dbfs - 80.0
                    else:
                        # SDRplay or other: use existing offset
                        dbm_estimate = dbfs
                    
                    if DEBUG:
                        print(f'rssi: {dev._device_type} computed dBFS={dbfs:.2f}, estimated dBm={dbm_estimate:.2f}')
                    
                    # Cache this valid value
                    _sample_rssi_from_device.last_valid[id(dev)] = dbm_estimate
                    return dbm_estimate
                else:
                    # No samples read, return last valid value
                    return _sample_rssi_from_device.last_valid.get(id(dev))
            except Exception as e:
                if DEBUG:
                    print(f'rssi: {dev._device_type} read error: {e}')
                # Return last valid value on error
                return _sample_rssi_from_device.last_valid.get(id(dev))
        
        # 1) Direct attribute (some devices may expose 'rssi')
        if hasattr(dev, 'rssi'):
            try:
                return float(getattr(dev, 'rssi'))
            except Exception:
                pass

        # 2) Some drivers expose an IIO attribute under the rx channel
        try:
            if hasattr(dev, '_get_iio_attr'):
                try:
                    val = dev._get_iio_attr('voltage0', 'rssi', False)
                    if val is not None:
                        return float(val)
                except Exception:
                    pass
        except Exception:
            pass

        # 3) Try to read a short RX buffer and compute power (may not be supported)
        try:
            if hasattr(dev, 'rx'):
                try:
                    import numpy as _np
                    try:
                        samples = dev.rx(1024)
                    except TypeError:
                        samples = dev.rx()
                    if samples is None:
                        return None
                    arr = _np.asarray(samples)
                    if arr.size == 0:
                        return None
                    # assemble complex IQ if interleaved
                    if arr.ndim == 2 and arr.shape[1] == 2:
                        raw_i = arr[:,0]
                        raw_q = arr[:,1]
                        # detect integer vs float samples
                        if _np.issubdtype(raw_i.dtype, _np.integer):
                            maxval = float(_np.iinfo(raw_i.dtype).max)
                            if maxval == 0:
                                return None
                            iq = (raw_i.astype(float) + 1j * raw_q.astype(float)) / maxval
                        else:
                            # floats: detect if values are large (scaled integers cast to float)
                            peak = max(float(_np.max(_np.abs(raw_i))), float(_np.max(_np.abs(raw_q)))) if raw_i.size else 0.0
                            if peak > 2.0:
                                # normalize by peak to get into -1..1 range
                                iq = (raw_i.astype(float) + 1j * raw_q.astype(float)) / peak
                            else:
                                iq = raw_i + 1j * raw_q
                    else:
                        # single-channel complex or float array
                        if _np.iscomplexobj(arr):
                            iq = arr
                        else:
                            # if integer interleaved as flat, try to reshape
                            if _np.issubdtype(arr.dtype, _np.integer) and arr.size % 2 == 0:
                                flat = arr.astype(float)
                                maxval = float(_np.iinfo(arr.dtype).max)
                                re = flat[0::2] / maxval
                                im = flat[1::2] / maxval
                                iq = re + 1j * im
                            else:
                                # floats: if samples appear large, normalize by peak
                                if _np.issubdtype(arr.dtype, _np.floating):
                                    peak = float(_np.max(_np.abs(arr))) if arr.size else 0.0
                                    if peak > 2.0:
                                        # try to interpret as interleaved real/imag
                                        if arr.size % 2 == 0:
                                            flat = arr.astype(float)
                                            re = flat[0::2]
                                            im = flat[1::2]
                                            ppeak = max(float(_np.max(_np.abs(re))), float(_np.max(_np.abs(im)))) if re.size else 0.0
                                            if ppeak > 2.0:
                                                iq = (re + 1j * im) / ppeak
                                            else:
                                                iq = re + 1j * im
                                        else:
                                            # normalize by peak
                                            iq = arr.astype(float) / peak
                                    else:
                                        iq = arr
                                else:
                                    iq = arr

                    # compute mean power (linear), normalized for integer ADCs -> dBFS
                    p = _np.mean(_np.abs(iq)**2)
                    if p <= 0:
                        return None
                    dbfs = 10.0 * math.log10(float(p))
                    if DEBUG:
                        print('rssi: computed dbfs=', dbfs, 'from dtype=', arr.dtype)
                    # return dBFS-like value (<= 0 for normalized integer ADCs)
                    return dbfs
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass
    return None


def start_rssi_sampler(dev, stop_event: threading.Event, rssi_log_callback=None):
    """Background thread: sample RSSI at 50 Hz (or 10 Hz for RTL-SDR) and store only the last sample.
    No averaging is performed; `current_status['rssi_last']` holds the raw
    dB-like value from `_sample_rssi_from_device()` and
    `current_status['rssi_last_dbm']` is the calibrated dBm using `RSSI_OFFSET`.
    
    Args:
        rssi_log_callback: Optional callback function(rssi_dbm) to be called on each sample
    """
    if dev is None:
        return

    def _worker():
        # Use 20 Hz for RTL-SDR to reduce USB bandwidth issues, 50 Hz for others
        if hasattr(dev, '_device_type') and dev._device_type == 'rtlsdr':
            interval = 1.0 / 20.0  # 20 Hz for RTL-SDR
        else:
            interval = 1.0 / 50.0  # 50 Hz for others
        while not stop_event.is_set():
            try:
                v = _sample_rssi_from_device(dev)
            except Exception:
                v = None

            # store the last raw sample (may be None)
            try:
                if v is None:
                    current_status['rssi_last'] = None
                    current_status['rssi_last_dbm'] = None
                    current_status['rssi_dbm'] = None
                else:
                    lv = float(v)
                    current_status['rssi_last'] = lv
                    # calibrated dBm using RSSI_OFFSET
                    try:
                        dbm = lv + float(RSSI_OFFSET)
                    except Exception:
                        dbm = None
                    # Display convention: show negative dBm
                    # For SoapySDR devices (RTL-SDR, SDRplay), the value is already in correct sign
                    # For Pluto/pyadi-iio, values need to be negated
                    try:
                        if dbm is None:
                            display_dbm = None
                        else:
                            # Check if device returns pre-signed values (SoapySDR devices)
                            if hasattr(dev, '_device_type'):
                                # SoapySDR devices already return properly signed dBm estimates
                                display_dbm = float(dbm)
                                if DEBUG:
                                    print(f'RSSI: SoapySDR device, dbm={dbm}, display_dbm={display_dbm}')
                            else:
                                # Pluto and other pyadi-iio devices: negate the value
                                display_dbm = -float(dbm)
                                if DEBUG:
                                    print(f'RSSI: Pluto device, dbm={dbm}, display_dbm={display_dbm}')
                    except Exception:
                        display_dbm = None
                    current_status['rssi_last_dbm'] = display_dbm
                    # backward-compatible alias: rssi_dbm -> last sample dBm (display)
                    current_status['rssi_dbm'] = display_dbm
                    
                    # Call logging callback if provided
                    if rssi_log_callback and display_dbm is not None:
                        try:
                            rssi_log_callback(display_dbm)
                        except Exception as e:
                            print(f'RSSI log callback error: {e}')

                    # If sample exceeds threshold, queue event (and optionally log to file)
                    try:
                        if (display_dbm is not None) and (display_dbm >= float(SIGNAL_MIN_DB)):
                            # Prepare event data
                            lat = current_position.get('lat')
                            lon = current_position.get('lon')
                            gps_time = current_status.get('last_time')
                            wall_time = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                            # If logging is enabled, append to file
                            if SIGNAL_LOG_FILE:
                                line = f"{wall_time},{gps_time},{lat},{lon},{display_dbm}\n"
                                try:
                                    with open(SIGNAL_LOG_FILE, 'a', encoding='utf-8') as fh:
                                        fh.write(line)
                                except Exception:
                                    pass

                            # queue event for GUI
                            try:
                                # Estimate range (meters) where the signal would drop to the
                                # configured detection threshold using free-space path loss.
                                # Using the ratio form of FSPL, distance scales with 10^(delta_dB/20).
                                try:
                                    thresh = float(SIGNAL_MIN_DB)
                                    if display_dbm is None:
                                        range_m = None
                                    else:
                                        # Use the threshold minus the measured display dBm
                                        # so that more-negative (weaker) measured RSSI
                                        # produces a larger estimated range.
                                        delta_db = thresh - float(display_dbm)
                                        # assume reference distance of 1 meter
                                        range_m = float(10 ** (delta_db / 20.0))
                                except Exception:
                                    range_m = None
                                # The GUI will decide whether to draw the circle based on its
                                # configured threshold; include RSSI and range in the event.
                                ev = {'time': wall_time, 'gps_time': gps_time, 'lat': lat, 'lon': lon, 'rssi': display_dbm, 'range_m': range_m}
                                with signal_event_lock:
                                    signal_event_queue.append(ev)
                            except Exception:
                                pass
                    except Exception:
                        pass
            except Exception:
                current_status['rssi_last'] = None
                current_status['rssi_last_dbm'] = None
                current_status['rssi_dbm'] = None

            time.sleep(interval)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    


def get_current_position():
    # Return (lat, lon) or (None, None)
    return current_position.get('lat'), current_position.get('lon')


def get_and_clear_signal_events():
    """Return and clear queued signal events (thread-safe). Each event is a dict with
    keys: time (ISO), gps_time, lat, lon, rssi (display dBm).
    """
    with signal_event_lock:
        if not signal_event_queue:
            return []
        evs = signal_event_queue[:]
        signal_event_queue.clear()
        return evs


def get_logs():
    """Return and clear new log messages (thread-safe)."""
    with gui_log_lock:
        if not gui_log:
            return []
        msgs = gui_log[:]
        gui_log.clear()
        return msgs


def get_status():
    """Return a copy of current GPS status (fix quality, num_sats, rmc_status, last_time)."""
    st = dict(current_status)
    # Note: rssi_last_dbm and rssi_dbm are already set correctly by the RSSI sampler thread
    # No need to recalculate them here - just return the status as-is
    # The old code here was recalculating and negating values, which caused issues with
    # SoapySDR devices that already return properly signed values
    
    # Provide calibrated dBm values for average and max if present (these are legacy)
    try:
        if st.get('rssi_avg') is not None:
            try:
                st['rssi_avg_dbm'] = - (float(st['rssi_avg']) + float(RSSI_OFFSET))
            except Exception:
                st['rssi_avg_dbm'] = None
        else:
            st['rssi_avg_dbm'] = None
    except Exception:
        st['rssi_avg_dbm'] = None
    try:
        if st.get('rssi_max') is not None:
            try:
                st['rssi_max_dbm'] = - (float(st['rssi_max']) + float(RSSI_OFFSET))
            except Exception:
                st['rssi_max_dbm'] = None
        else:
            st['rssi_max_dbm'] = None
    except Exception:
        st['rssi_max_dbm'] = None
    
    # rssi_last_dbm and rssi_dbm are already set by the sampler thread, don't override them
    # Just ensure rssi_dbm alias exists
    if 'rssi_dbm' not in st or st['rssi_dbm'] is None:
        st['rssi_dbm'] = st.get('rssi_last_dbm')
    
    return st


# Logs are kept on console; no peek/ack helpers required


def parse_args():
    p = argparse.ArgumentParser(description="SigFinder: GPS + SDR signal mapper")
    p.add_argument("--gps-port", help="GPS serial port (e.g. /dev/ttyUSB0)")
    p.add_argument("--gps-baud", type=int, default=4800, help="GPS baud rate (default: 4800)")
    p.add_argument("--sdr-type", choices=['pluto', 'sdrplay', 'rtlsdr'], default='pluto', help="SDR hardware type: pluto, sdrplay, or rtlsdr (default: pluto)")
    p.add_argument("--pluto-uri", default=None, help="Pluto URI (e.g. ip:192.168.2.1); omit for autodetect")
    p.add_argument("--sdr-gain", type=float, default=40.0, help="SDR gain in dB (for SDRplay/RTL-SDR, default: 40.0; use 0 or negative for RTL-SDR AGC)")
    p.add_argument("--freq", required=True, help="Frequency in MHz (e.g. 433.5")
    p.add_argument("--rx-bw", type=float, default=125.0, help="RX bandwidth in kHz (default: 125)")
    p.add_argument("--rssi-offset", type=float, default=0.0, help="Calibration offset (dB) to convert measured RSSI to approximate dBm")
    p.add_argument("--gui", action="store_true", help="Open GUI with map and buttons")
    p.add_argument("--debug", action="store_true", help="Enable verbose GPS parsing debug prints")
    p.add_argument("--signal-log-file", default=None, help="Path to append detected signals (CSV)."
                   )
    p.add_argument("--signal-min-db", type=float, default=-120.0, help="Minimum display dBm (negative) to consider a detection")
    return p.parse_args()


def main():
    args = parse_args()

    # honor debug flag from CLI
    try:
        global DEBUG
        DEBUG = bool(getattr(args, 'debug', False))
    except Exception:
        pass

    # Load persisted config (if any). Config format: {"range_trigger": -110.0, "last_position": {"lat": ..., "lon": ...}}
    def load_config():
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, 'r', encoding='utf-8') as fh:
                    return json.load(fh)
        except Exception:
            pass
        return {}

    def save_config(cfg: dict):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            # load existing and merge so callers can provide partial updates
            base = {}
            try:
                if os.path.exists(CONFIG_PATH):
                    with open(CONFIG_PATH, 'r', encoding='utf-8') as fh:
                        base = json.load(fh) or {}
            except Exception:
                base = {}
            base.update(cfg or {})
            with open(CONFIG_PATH, 'w', encoding='utf-8') as fh:
                json.dump(base, fh, indent=2)
        except Exception:
            pass

    cfg = load_config()
    # Default initial range trigger: prefer config, otherwise use -100 dBm instead of previous -110
    initial_range_default = float(cfg.get('range_trigger', -100.0))
    # Load last known position into current_position so GUI can start near it
    try:
        lp = cfg.get('last_position')
        if lp and isinstance(lp, dict):
            lat = lp.get('lat')
            lon = lp.get('lon')
            if lat is not None and lon is not None:
                try:
                    current_position['lat'] = float(lat)
                    current_position['lon'] = float(lon)
                except Exception:
                    pass
    except Exception:
        pass
    # Load initial map center/zoom if present
    initial_map_center = None
    initial_map_zoom = None
    try:
        mc = cfg.get('map_center')
        if mc and isinstance(mc, dict):
            lat = mc.get('lat')
            lon = mc.get('lon')
            if lat is not None and lon is not None:
                try:
                    initial_map_center = (float(lat), float(lon))
                except Exception:
                    initial_map_center = None
        mz = cfg.get('map_zoom')
        if mz is not None:
            try:
                initial_map_zoom = int(mz)
            except Exception:
                initial_map_zoom = None
    except Exception:
        initial_map_center = None
        initial_map_zoom = None
    
    try:
        freq_mhz = float(args.freq)
    except Exception:
        print("Invalid frequency. Use a number in MHz, e.g. 433.5")
        sys.exit(2)
    freq_hz = int(freq_mhz * 1e6)

    stop_event = threading.Event()
    gps_thread = None
    # Validate GPS port before attempting to start the reader thread.
    # Some paths (e.g. /dev/null) or missing devices can cause underlying
    # serial drivers to raise errors; prefer to skip starting the thread
    # when the port is clearly not usable.
    try:
        gps_port_val = getattr(args, 'gps_port', None)
    except Exception:
        gps_port_val = None

    if gps_port_val:
        try:
            # Treat /dev/null as "no GPS"
            if str(gps_port_val) == '/dev/null':
                print('GPS: /dev/null given, skipping GPS reader')
                gps_port_val = None
        except Exception:
            gps_port_val = None

    if gps_port_val:
        try:
            # Treat missing device files as 'no GPS' but otherwise attempt to
            # start the GPS reader and let the reader handle open errors.
            # This is less strict than requiring a character device, and
            # avoids skipping valid ports that may not show as S_ISCHR
            # in some container or udev setups.
            if not os.path.exists(gps_port_val):
                print(f"GPS: port {gps_port_val} does not exist; skipping GPS reader")
                gps_port_val = None
        except Exception:
            # If any unexpected error occurs checking the path, attempt to
            # start the GPS reader and let it report the failure.
            pass

    if gps_port_val:
        try:
            gps_thread = threading.Thread(target=gps_reader, args=(gps_port_val, args.gps_baud, stop_event), daemon=True)
            gps_thread.start()
        except Exception as e:
            print(f"Failed to start GPS thread for {gps_port_val}: {e}")
            gps_thread = None
    # rx_bw provided in kHz on CLI; convert to Hz
    try:
        rx_bw_khz = float(getattr(args, 'rx_bw', 125.0))
    except Exception:
        rx_bw_khz = 125.0
    rx_bw_hz = int(rx_bw_khz * 1000)
    # configure signal logging globals
    global SIGNAL_LOG_FILE, SIGNAL_MIN_DB
    try:
        SIGNAL_LOG_FILE = args.signal_log_file if args.signal_log_file else None
    except Exception:
        SIGNAL_LOG_FILE = None
    try:
        SIGNAL_MIN_DB = float(getattr(args, 'signal_min_db', SIGNAL_MIN_DB))
    except Exception:
        pass
    
    # Configure SDR based on selected type
    sdr_device = None
    sdr_type = getattr(args, 'sdr_type', 'pluto')
    
    if sdr_type == 'sdrplay':
        try:
            sdr_gain = float(getattr(args, 'sdr_gain', 40.0))
        except Exception:
            sdr_gain = 40.0
        sdr_device = configure_sdrplay(freq_hz, rx_bw_hz, sdr_gain)
        if sdr_device:
            print(f'main: SDRplay device configured successfully')
        else:
            print(f'main: Failed to configure SDRplay device')
    elif sdr_type == 'rtlsdr':
        try:
            sdr_gain = float(getattr(args, 'sdr_gain', 40.0))
        except Exception:
            sdr_gain = 40.0
        sdr_device = configure_rtlsdr(freq_hz, rx_bw_hz, sdr_gain)
        if sdr_device:
            print(f'main: RTL-SDR device configured successfully')
        else:
            print(f'main: Failed to configure RTL-SDR device')
    else:  # default to pluto
        sdr_device = configure_pluto(args.pluto_uri, freq_hz, rx_bw_hz)
        if sdr_device:
            print(f'main: Pluto device configured successfully')
        else:
            print(f'main: Failed to configure Pluto device')
    
    # diagnostic print to confirm SDR presence
    try:
        if DEBUG:
            if sdr_device is None:
                print(f'main: SDR device ({sdr_type}) not available; RSSI sampler will not run')
            else:
                print(f'main: SDR device ({sdr_type}) opened successfully')
    except Exception:
        pass
    # If we have an SDR device, start an RSSI sampler thread that updates current_status
    # Support multiple RSSI callbacks so logging can be independent of the GUI.
    rssi_callbacks = []

    def add_rssi_callback(callback):
        """Register a callback to be called for each RSSI sample.

        Callbacks will be invoked with a single argument: rssi_dbm (float).
        """
        try:
            if callback and callable(callback):
                rssi_callbacks.append(callback)
        except Exception:
            pass

    def remove_rssi_callback(callback):
        try:
            if callback in rssi_callbacks:
                rssi_callbacks.remove(callback)
        except Exception:
            pass

    def rssi_callback_wrapper(rssi_dbm):
        # Invoke all registered callbacks safely
        for cb in list(rssi_callbacks):
            try:
                cb(rssi_dbm)
            except Exception as e:
                print(f'RSSI callback error: {e}')

    # Simple file-based logger that runs in the main process and does not depend on GUI
    class FileLogger:
        def __init__(self, directory=None, prefix='auto_log'):
            import os, time, threading
            self.dir = directory or os.getcwd()
            self.lock = threading.Lock()
            ts = time.strftime('%Y-%m-%d_%H-%M-%S')
            self.filename = os.path.join(self.dir, f"{prefix}_{ts}.csv")
            self.fh = None
            self.paused = False
            try:
                os.makedirs(self.dir, exist_ok=True)
                self.fh = open(self.filename, 'a', encoding='utf-8', newline='')
                # Write header if file empty
                try:
                    if self.fh.tell() == 0:
                        self.fh.write('Timestamp,Latitude,Longitude,Fix Quality,Num Satellites,RMC Status,RSSI (dBm)\n')
                        self.fh.flush()
                except Exception:
                    pass
                print(f'main: FileLogger created -> {self.filename}')
            except Exception as e:
                print(f'main: Failed to create FileLogger file: {e}')

        def log(self, rssi_dbm):
            if self.paused or self.fh is None:
                return
            try:
                from datetime import datetime
                # Use helper functions to fetch latest position/status
                lat, lon = get_current_position()
                st = get_status()
                timestamp = datetime.utcnow().isoformat() + 'Z'
                line = f"{timestamp},{lat if lat is not None else ''},{lon if lon is not None else ''},{st.get('fix_quality','')},{st.get('num_sats','')},{st.get('rmc_status','')},{rssi_dbm if rssi_dbm is not None else ''}\n"
                with self.lock:
                    self.fh.write(line)
                    self.fh.flush()
            except Exception as e:
                print(f'main: FileLogger write error: {e}')

        def close(self):
            try:
                if self.fh:
                    self.fh.close()
            except Exception:
                pass

        def pause(self):
            self.paused = True

        def resume(self):
            self.paused = False

    # Do NOT auto-start file logging if GUI is enabled; file logging will be
    # started automatically only when running without GUI, or when the GUI
    # user explicitly starts a session (GUI will register its callback).
    file_logger = None

    if sdr_device is not None:
        try:
            start_rssi_sampler(sdr_device, stop_event, rssi_callback_wrapper)
        except Exception as e:
            print('Failed to start RSSI sampler:', e)

    # If running without GUI, automatically create and register the FileLogger so
    # logging continues even when no GUI is present. If GUI is enabled, the GUI
    # will register its own logging callback when the user starts a session.
    try:
        if not args.gui:
            file_logger = FileLogger()
            add_rssi_callback(file_logger.log)
    except Exception as e:
        print(f'main: Failed to create auto FileLogger: {e}')

    if args.gui:
        # Prefer PyQt GUI if available, otherwise fall back to webview GUI
        gui_module = None
        try:
            from . import gui_pyqt as gui_module
            print("main: Loaded gui_pyqt module")
        except Exception as e:
            print(f"main: Failed to load gui_pyqt: {e}")
            try:
                from . import gui as gui_module
                print("main: Loaded gui (webview) module")
            except Exception as e:
                print(f"GUI dependencies not available: {e}")
                print("Install requirements and retry.")
                stop_event.set()
                sys.exit(1)

        # Start GUI; gui.start_gui will block until GUI closed
        try:
            # Try to call the newer GUI signature including initial range and a config save callback
            try:
                print(f"main: Calling {gui_module.__name__}.start_gui with rssi_callback_setter")
                gui_module.start_gui(get_current_position, get_status, get_and_clear_signal_events, initial_range_default, config_save_callback=save_config, rssi_callback_setter=add_rssi_callback, rssi_callback_remover=remove_rssi_callback)
            except TypeError as te:
                print(f"main: TypeError with rssi_callback_setter: {te}")
                # Fallback without rssi_callback_setter
                try:
                    print(f"main: Calling {gui_module.__name__}.start_gui with 5 args")
                    gui_module.start_gui(get_current_position, get_status, get_and_clear_signal_events, initial_range_default, config_save_callback=save_config)
                except TypeError as te:
                    print(f"main: TypeError with 5 args: {te}")
                # fallback to 4-arg signature (no config callback)
                try:
                    print(f"main: Calling {gui_module.__name__}.start_gui with 4 args")
                    gui_module.start_gui(get_current_position, get_status, get_and_clear_signal_events, initial_range_default)
                except TypeError as te2:
                    print(f"main: TypeError with 4 args: {te2}")
                    # fallback to older 2-argument signature
                    try:
                        print(f"main: Calling {gui_module.__name__}.start_gui with 2 args")
                        gui_module.start_gui(get_current_position, get_status)
                    except TypeError as te3:
                        print(f"main: TypeError with 2 args: {te3}")
                        print(f"main: Calling {gui_module.__name__}.start_gui with 1 arg")
                        gui_module.start_gui(get_current_position)
        except ModuleNotFoundError as e:
            print('GUI start failed; missing dependency:', e)
            print('Install PyQt6 (for Qt GUI) or pywebview (for webview GUI) and retry.')
            stop_event.set()
            sys.exit(1)
        except KeyboardInterrupt:
            print("GUI interrupted; exiting.")
        except Exception as e:
            print('Failed to start GUI:', e)
            stop_event.set()
            sys.exit(1)
        finally:
            stop_event.set()
            if gps_thread is not None:
                gps_thread.join(timeout=2)
            # Cleanup SDR device
            if sdr_device is not None:
                try:
                    # Clean up SoapySDR stream if present
                    if hasattr(sdr_device, '_rx_stream'):
                        try:
                            sdr_device.deactivateStream(sdr_device._rx_stream)
                            sdr_device.closeStream(sdr_device._rx_stream)
                        except Exception:
                            pass
                    # pyadi-iio cleanup: deleting device often closes handles
                    del sdr_device
                except Exception:
                    pass
            # Close file logger if present
            try:
                if 'file_logger' in locals() and file_logger:
                    file_logger.close()
            except Exception:
                pass
            # Close file logger if present
            try:
                if 'file_logger' in locals() and file_logger:
                    file_logger.close()
            except Exception:
                pass
    else:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Exiting...")
        finally:
            stop_event.set()
            if gps_thread is not None:
                gps_thread.join(timeout=2)
            # Cleanup SDR device
            if sdr_device is not None:
                try:
                    # Clean up SoapySDR stream if present
                    if hasattr(sdr_device, '_rx_stream'):
                        try:
                            sdr_device.deactivateStream(sdr_device._rx_stream)
                            sdr_device.closeStream(sdr_device._rx_stream)
                        except Exception:
                            pass
                    # pyadi-iio cleanup: deleting device often closes handles
                    del sdr_device
                except Exception:
                    pass
    main()
