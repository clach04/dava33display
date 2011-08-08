#!/usr/bin/env python
# -*- coding: ascii -*-
# vim:ts=4:sw=4:softtabstop=4:smarttab:expandtab
#
# asusdisplay.py - Loads an image on the USB TFT display of ASUS A33 DAV
# Copyright (C) 2011  Chris Clark
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
"""Python version of asusdisplay.c

Main differences compared with C version:
  * Requires Python 2.x, PIL, pyusb 1.x (does not work with pyusb 0.1,
    but does work with libusb-0.1. pyusb revision 90 from svn works fine)
  * Should work with any USB library on any platform
      * Tested with Linux:
          * 32 bit Tiny Core with:
              * libusb-0.1
              * libusb-1.0
              * libusb-1.0 with libusb-0.1 compatibility layer
                (C version hangs/crashes using compatibility layer)
          * Ubuntu 10.10 32 bit:
              * libusb-0.1
              * libusb-1.0
          * Ubuntu 10.10 64 bit:
              * libusb-0.1
              * libusb-1.0
  * Can load ANY image format, with any size supported by PIL
      * NOTE small images end up with black bar(s)
      * this can load the testimg.bmp provided in SVN repo
  * Doesn't really understand the protocol (or packet contents) used,
    see C code and documents for more detail on the protocol
  * Currently only loads an image (no time support)
  * Currently only loads image then quits (no multiple image update)

NOTE it is important to allow asusdisplay to complete an IO cycle
(e.g. complete image load) before interupting, aborting part way through
can leave the display locked until the next reboot.
I've not yet looked at doing resets to recover from this situation.
"""

import os
import sys
import string
import re
import random
import urllib2
import time
try:
    import cStringIO as StringIO
except ImportError:
    import StringIO

try:
    from PIL import Image    # http://www.pythonware.com/products/pil/
    from PIL import ImageFont, ImageDraw, ImageOps
except ImportError:
    try:
        import Image    # http://www.pythonware.com/products/pil/
        import ImageFont, ImageDraw, ImageOps
    except ImportError:
        raise  # Potential to remove dependency on PIL


DEBUG = False

if DEBUG:
    """Horrible mock objects that do NOT emulate usb lib well at all...
    ....but it works well enough for this on machines without the correct
    hardware.
    """
    
    class FakeDev(object):
        iProduct = iManufacturer = idProduct = idVendor = 1
        
        def __init__(self):
            self.__count = 0
        
        def detach_kernel_driver(self, x):
            pass
        
        def set_configuration(self):
            pass
        
        def reset(self):
            pass
        
        def write(self, ep, block, interface, timeout):
            self.__count += 1
            print self.__count, 'Fake WRITE', len(block)
            pass
        
        def read(self, ep, size, interface, timeout):
            self.__count += 1
            
            result = range(size)
            print self.__count, 'Fake READ', len(result)
            return result
    
    class Fake(object):
        def find(self, idVendor, idProduct):
            return FakeDev()
    usb = Fake()
    usb.core = Fake()
else:
    # Import http://sourceforge.net/projects/pyusb/
    import usb.core
    import usb.util


MAX_IMAGE_SIZE = (320, 240)

#clock_font = ImageFont.load_default()
clock_font = None
for font_filename, font_size in [
                                #('orbitron-black.ttf', 60),  # not proportional
                                #('orbitron-bold.ttf', 60),
                                #('orbitron-medium.ttf', 60),
                                ('FreeSansBold.ttf', 72),
                                ('/usr/share/fonts/truetype/freefont/FreeSansBold.ttf', 72),
                                ('/usr/share/fonts/luxisr.ttf', 72),  # this leaves some spacce on RHS
                                ]:
    try:
        clock_font = ImageFont.truetype(font_filename, font_size)
        print font_filename, font_size
        break
    except IOError:
        pass
# FIXME set clock color/colour, this really should be a parameter/config setting
#clock_color = (255, 0, 0)
clock_color = (255, 255, 255)  # white matches what c version of asusdisplay

def simpleimage_clock(im):
    """Apply timestamp to image.
    This is NOT (yet?) the same format as c version of asusdisplay
    """
    my_text = time.strftime('%H:%M:%S')
    d = ImageDraw.Draw(im)
    d.text((0, 0), my_text, font=clock_font, fill=clock_color)
    
    return im

def simpleimage_resize(im):
    if im.size > MAX_IMAGE_SIZE:
        print 'resizing'
        """resize - maintain aspect ratio
        NOTE PIL thumbnail method does not increase
        if new size is larger than original
        2 passes gives good speed and quality
        """
        im.thumbnail((MAX_IMAGE_SIZE[0] * 2, MAX_IMAGE_SIZE[1] * 2))
        im.thumbnail(MAX_IMAGE_SIZE, Image.ANTIALIAS)
    
    # image is not too big, but it may be too small
    # _may_ need to add black bar(s)
    if im.size < MAX_IMAGE_SIZE:
        print 'too small - add bar'
        im = im.convert('RGB')  # convert to RGB
        bg_col = (0, 0, 0)
        background = Image.new('RGB', MAX_IMAGE_SIZE, bg_col)
        x, y = im.size
        background.paste(im, (0, 0, x, y))  # does not center/centre
        im = background
    
    return im

def image2raw(im):
    """Convert a PIL image into raw format suitable for ASUS A33 DAV screen
    
    returns raw buffer
    """
    
    im = simpleimage_resize(im)  # do not assume image is correct size
    
    """ convert to RGB
    - TODO add check around this, image may alreayd be RGB"""
    im = im.convert('RGB')
    x = im.getdata()
    newbuff = ''.join([''.join(map(chr, rgb_tuple)) for rgb_tuple in x])
    return newbuff

def process_image(im, include_clock=True):
    im = simpleimage_resize(im)
    if include_clock:
        simpleimage_clock(im)
    rawimage = image2raw(im)
    return rawimage


def raw2png(raw_filename, image_filename):
    """Diagnostic to dump a viewable (PNG) of raw image
    """
    print 'reading', raw_filename
    f = open(raw_filename, 'rb')
    binstr = f.read()
    f.close()
    
    im = Image.fromstring('RGB', (320, 240), binstr)
    x = im.getdata()
    im.save(image_filename)

    print 'wrote', image_filename


ASUS_VENDOR_ID = 0x1043
ASUS_PRODUCT_ID = 0x82B2

ImgHeader = [0x02, 0x00, 0x20, 0x00, 0x20, 0x84, 0x03,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x40, 0x01, 0xF0, 0x00, 0x00, 0x00,
            0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00]
ImgHeader = ''.join(map(chr, ImgHeader))  # convert to "string" (byte buffer)


class DavDisplay(object):
    def __init__(self):
        """
        NOTE this really should be a Highlander object, There Can Be Only One!
        """
        self.packet_count = 0
        self.dev = None
        self._platform = os.name
    
    def displayinit(self):
        """Similar to C version of () and displayinit()
        
        NOTE missing explicit:
           * usb_clear_halt()
           * usb_resetep()
        """
        dev = usb.core.find(idVendor=ASUS_VENDOR_ID, idProduct=ASUS_PRODUCT_ID)

        if dev is None:
            raise ValueError('Device not found')
        
        # NOTE sometimes one of these fails and needs to be re-ran.
        # I've not yet worked out a robust way to deal with this :-(
        try:
            dev.set_configuration()
        except usb.core.USBError, info:
            pass  # assume everything is OK
        try:
            dev.detach_kernel_driver(1)
        except usb.core.USBError, info:
            pass  # assume everything is OK
        except AttributeError, info:
            # Ignore under Windows, missing with libusb-0.1
            # NOTE no backend check below, just platform
            if self._platform != 'nt':
                raise
        
        self.dev = dev
        
        # packet #1 write
        data = 'USBC\x00\x00\x00\x00\t\x00\x00\x00\x00\x00\x0c\xe6\x0b\x00\x00\x00\t\x00\x00\x00\t\x00\x00\x00\x00\x00\x00'
        self.write(0x02, data)

        # packet #2 write
        data = '\x0b\xb2\x08\x00\t\x00\x00\x00\x01'
        self.write(0x02, data)

        # packet #3 read
        result_data = self.read(0x81, 13)
        #assert len(data) == 13, '%d != 13' % (len(data), )   # under Python may see 9? (TODO CHECK newlines?)
    
    def close(self):
        """Similar to C version of close
        """
        if self._platform != 'nt':
            self.dev.reset()
        #del(self.dev)  #? TODO
    
    def sendimage(self, rawimage):
        """Similar to C version of sendimage()
        
        @param rawimage - the raw image to send
        """
        # packet #4 write - Informs devices the first part of the image data is coming next
        data = 'USBC\xa1i\x00\x00\x00\x00\x01\x00\x00\x00\x0c\xe6\x02\x00\x01\x00\x00\x00\x03\x84 \x00\x00\x00\x00\x00\x00'
        self.write(0x02, data)

        """
        # send image in 3 chunks (including an image header)
        image p1 32 + 65504  -- where 32 is the length of the image header
        image p2 65536
        image p3 65536
        """

        # packet #5 write - First of Image data, includes Image Header
        data = ImgHeader + rawimage[:65504]
        self.write(0x02, data)

        # packet #6 read
        result_data = self.read(0x81, 13)
        #assert len(data) == 13, '%d != 13' % (len(data), )   # under Python may see 9? (TODO CHECK newlines?)

        # packet #7 write
        data = 'USBC\xa2i\x00\x00\x00\x00\x01\x00\x00\x00\x0c\xe6\x02\x00\x01\x00\x00\x00\x03\x84 \x01\x00\x00\x00\x00\x00'
        self.write(0x02, data)

        # packet #8 write - Second of Image data
        data = rawimage[65504:65504+65536]
        self.write(0x02, data)

        # packet #9 read
        result_data = self.read(0x81, 13)
        #assert len(data) == 13, '%d != 13' % (len(data), )   # under Python may see 9? (TODO CHECK newlines?)

        # packet #10 write
        data = 'USBC\xa3i\x00\x00\x00\x00\x01\x00\x00\x00\x0c\xe6\x02\x00\x01\x00\x00\x00\x03\x84 \x02\x00\x00\x00\x00\x00'
        self.write(0x02, data)

        # packet #11 write - Third of Image data
        data = rawimage[65504+65536:65504+65536+65536]
        self.write(0x02, data)

        # packet #12 read
        result_data = self.read(0x81, 13)
        #assert len(data) == 13, '%d != 13' % (len(data), )   # under Python may see 9? (TODO CHECK newlines?)

        # packet #13 write
        data = 'USBC\xa4i\x00\x00 \x84\x00\x00\x00\x00\x0c\xe6\x02\x00\x00\x84 \x00\x03\x84 \x03\x00\x00\x00\x00\x00'
        self.write(0x02, data)

        # packet #14 write - Fourth/Last of Image data
        data = rawimage[65504+65536+65536:]
        self.write(0x02, data)

        # packet #15 read
        result_data = self.read(0x81, 13)
        #assert len(data) == 13, '%d != 13' % (len(data), )   # under Python may see 9? (TODO CHECK newlines?)
        
    def write(self, ep, block):
        """Similar to C version of writedata
        
        Writes a block of size data to the device, if an error happens then
        exception is raised.
        
        C: int writedata(int ep, void *block, int size)
        Python dev as param 1, no size needed (uses all of block).
        No return value.
        """
        self.packet_count += 1
        # interface may need to specify bulk....
        self.dev.write(ep, block, interface=None, timeout=1000)
    
    def read(self, ep, size):
        """Similar to C version of readdata
        
        Reads data from the endpoint if an error happens then exception is
        raised.
        
        C: int readdata(int ep, void *block, int size)
        Python dev as param 1, no block passed in (returns data instead),
        size needed. returns data
        """
        self.packet_count += 1
        result = self.dev.read(ep, size, interface=None, timeout=1000)
        return result


def gen_images_urls(search_term=None, random_offset=True):
    """Quick-n-dirty random image URL generator.
    Uses google, and google's image cache and thus tends to only have small images
    Also google images tend to be "safe"
    """
    RE_IMAGEURL = re.compile('"(http.+?gstatic.com/images.+?)"')  # filter googles copies of the static images
    word_list = []
    charset = string.ascii_lowercase * 2 + string.digits
    
    if not search_term:
        # generate complete garbage - not a real (English) word
        for i in range(random.randint(2, 7)):
            word_list.append(random.choice(charset))
        search_term = ''.join(word_list)
    
    #limit_size = '&tbs=isz:ex,iszw:320,iszh:240'  # 320x240 - note only useful if getting original image
    limit_size = "&tbs=isz:lt,islt:2mp"  #  Larger than 2MP
    if random_offset:
        start_offset = (random.randint(0, 50) * 10)  # Randomize the start page
    else:
        start_offset = 0
    request_url = 'http://images.google.com/images?q=%s&start=%d' % (search_term, start_offset)
    request_url += limit_size
    request_hdr = {'User-Agent': 'random/1.0'}
    
    request = urllib2.Request(request_url, None, request_hdr)
    html = urllib2.urlopen(request).read()
    """TODO? detect "did not match any documents."? will need "&hl=en" adding
    NOTE at this point have links to "small" google static cache in html,
    also have embedded data:image (base64) slightly larger than "small"
    images that could be extracted and ran through mime"""
    
    matches = RE_IMAGEURL.findall(html)
    for hit in matches:
        if hit.startswith('http') and len(hit) < 128 and 'gstatic.com/images':
            # this complex if basically skips the first regexp hit (could just ignore matches[0] I supposed, really need to fix regx
            yield hit


def main(argv=None):
    if argv is None:
        argv = sys.argv
    
    # Super horrible command line checking
    do_random = False
    include_clock=True
    if '--no_clock' in argv:
        include_clock=False
    if '--random' in argv:
        do_random = True
    
    if do_random:
        # DEBUG mode, useful for soak testing to make sure LOTS of updates work
        print 'getting random images....'
        image_list = []
        for url in gen_images_urls(search_term='maps', random_offset=False):
            print url
            fobj = urllib2.urlopen(url)
            image_data = fobj.read()
            fileptr = StringIO.StringIO(image_data)  # fobj is missing seek() required by PIL
            im = Image.open(fileptr)
            rawimage = image2raw(im)
            image_list.append(rawimage)
    else:
        image_filename = argv[1]
        print 'reading', image_filename
        im = Image.open(image_filename)
        rawimage = process_image(im, include_clock=include_clock)

    display = DavDisplay()
    display.displayinit()
    if do_random:
        while 1:
            for rawimage in image_list:
                # TODO need fps
                display.sendimage(rawimage)
    else:
        display.sendimage(rawimage)
    display.close()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
