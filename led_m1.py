"""
M1 case ADP8866 RGB LED driver for Particle Tachyon.
I2C bus 1, address 0x27.

Channel mapping (confirmed on hardware):
  Red:   LED1/4/7 -> ISC registers 0x23, 0x26, 0x29
  Blue:  LED2/5/8 -> ISC registers 0x24, 0x27, 0x2A
  Green: LED3/6/9 -> ISC registers 0x25, 0x28, 0x2B

Physical LED positions (confirmed on hardware):
  LED1-3 (ISC 0x23-0x25) -> Bottom side LED
  LED4-6 (ISC 0x26-0x28) -> Top side LED
  LED7-9 (ISC 0x29-0x2B) -> Top LED

Zone layout:
  Top LED   -> music tracker app status (flash / pulse / breathe)
  Side LEDs -> owned by particled (cloud / charging status)

Passive mode: does not reconfigure the ADP8866 chip -- only writes
ISC registers for the top LED during music events.
"""

import os
import fcntl
import time
import threading
import logging

log = logging.getLogger(__name__)

_I2C_SLAVE = 0x0703
_BUS_PATH  = "/dev/i2c-1"
_ADDR      = 0x27

# Top LED zone only (LED7-9)
_TOP_RED   = 0x29
_TOP_GREEN = 0x2B
_TOP_BLUE  = 0x2A

_fd        = None
_lock      = threading.Lock()
_anim      = None
_anim_stop = threading.Event()


def _write(reg, val):
    if _fd is None:
        return
    try:
        os.write(_fd, bytes([reg, val & 0xFF]))
    except Exception as e:
        log.debug(f"LED i2c write error: {e}")


def init():
    """Open I2C bus in passive mode. Returns True on success."""
    global _fd
    try:
        fd = os.open(_BUS_PATH, os.O_RDWR)
        fcntl.ioctl(fd, _I2C_SLAVE, _ADDR)
        _fd = fd
        log.info("M1 LED driver ready (passive mode)")
        return True
    except Exception as e:
        log.warning(f"M1 LED open failed (LEDs disabled): {e}")
        _fd = None
        return False


def close():
    global _fd
    if _fd is not None:
        try:
            _clear_top()
            os.close(_fd)
        except Exception:
            pass
        _fd = None


def _set_top(r, g, b):
    r7 = max(0, min(255, r)) >> 1
    g7 = max(0, min(255, g)) >> 1
    b7 = max(0, min(255, b)) >> 1
    with _lock:
        _write(_TOP_RED,   r7)
        _write(_TOP_GREEN, g7)
        _write(_TOP_BLUE,  b7)


def _clear_top():
    _set_top(0, 0, 0)


def off():
    """Stop any animation and clear the top LED."""
    _cancel_anim()
    _clear_top()


def _cancel_anim():
    global _anim
    _anim_stop.set()
    if _anim and _anim.is_alive():
        _anim.join(timeout=0.5)
    _anim_stop.clear()


def flash(r, g, b, duration=1.0):
    """Hold color on top LED for duration seconds then clear. Non-blocking."""
    _cancel_anim()

    def _run():
        end = time.monotonic() + duration
        while time.monotonic() < end:
            if _anim_stop.is_set():
                break
            _set_top(r, g, b)
            time.sleep(0.02)
        _clear_top()

    global _anim
    _anim = threading.Thread(target=_run, daemon=True)
    _anim.start()


def pulse(r, g, b, steps=30, duration=2.0):
    """Fade in then fade out once on top LED. Non-blocking."""
    _cancel_anim()

    def _run():
        half = duration / 2
        step_time = half / steps
        for i in list(range(steps + 1)) + list(range(steps - 1, -1, -1)):
            if _anim_stop.is_set():
                break
            frac = i / steps
            _set_top(int(r * frac), int(g * frac), int(b * frac))
            time.sleep(step_time)
        _clear_top()

    global _anim
    _anim = threading.Thread(target=_run, daemon=True)
    _anim.start()


def breathe(r, g, b):
    """Breathe continuously on top LED until off() or another animation."""
    _cancel_anim()

    def _run():
        steps = 40
        while not _anim_stop.is_set():
            for i in list(range(steps + 1)) + list(range(steps, -1, -1)):
                if _anim_stop.is_set():
                    break
                frac = (i / steps) ** 2
                _set_top(int(r * frac), int(g * frac), int(b * frac))
                time.sleep(0.04)
        _clear_top()

    global _anim
    _anim = threading.Thread(target=_run, daemon=True)
    _anim.start()
