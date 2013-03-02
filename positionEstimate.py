import util, satPosition, rangeCorrection

class rawPseudoRange:
    '''class to hold raw range information from a receiver'''
    def __init__(self, gps_week, time_of_week):
        # time of week in seconds, including fractions of a second
        self.time_of_week = time_of_week;
        self.gps_week     = gps_week
        self.prMeasured   = {}
        self.quality      = {}

    def add(self, svid, prMes, quality):
        '''add a pseudo range for a given svid'''
        self.prMeasured[svid] = prMes
        self.quality[svid]    = quality
        

def positionErrorFunction(p, data):
    '''error function for least squares position fit'''
    pos = util.PosVector(p[0], p[1], p[2])
    recv_clockerr = p[3]
    ret = []
    for d in data:
        satpos, prange = d
        dist = pos.distance(satpos)
        ret.append(dist - (prange + util.speedOfLight*recv_clockerr))
    return ret

def positionLeastSquares(satinfo):
    '''estimate ECEF position of receiver via least squares fit to satellite positions and pseudo-ranges'''
    import scipy
    from scipy import optimize
    data = []

    pranges = satinfo.prCorrected
    
    for svid in satinfo.satpos:
        data.append((satinfo.satpos[svid], pranges[svid]))
    lastpos = satinfo.lastpos
    p0 = [lastpos.X, lastpos.Y, lastpos.Z, satinfo.receiver_clock_error]
    p1, ier = optimize.leastsq(positionErrorFunction, p0[:], args=(data))
    if not ier in [1, 2, 3, 4]:
        raise RuntimeError("Unable to find solution")

    newpos = util.PosVector(p1[0], p1[1], p1[2])
    satinfo.lastpos = newpos
    satinfo.receiver_clock_error = p1[3]
    return newpos


def positionEstimate(satinfo, raw):
    '''process raw messages to calculate position
    '''
    satinfo.reset();

    for svid in raw.prMeasured:

        if not satinfo.valid(svid):
            # we don't have ephemeris data for this space vehicle
            continue

        if raw.quality[svid] < 7:
            # for now we will ignore raw data that isn't very high quality. It would be
            # better to do a weighting in the least squares calculation
            continue

        # get the ephemeris and pseudo-range for this space vehicle
        ephemeris = satinfo.ephemeris[svid]
        prMes = raw.prMeasured[svid]

        # calculate the time of flight for this pseudo range
        tof = prMes / util.speedOfLight

        # assume the time_of_week is the exact receiver time of week that the message arrived.
        # subtract the time of flight to get the satellite transmit time
        transmitTime = raw.time_of_week - tof

        timesec = util.gpsTimeToTime(raw.gps_week, raw.time_of_week)

        # calculate the satellite position at the transmitTime
        satPosition.satPosition(satinfo, svid, transmitTime)
        Trel = satinfo.satpos[svid].extra

        # correct for earths rotation in the time it took the messages to get to the receiver
        satPosition.correctPosition(satinfo, svid, tof)

        # calculate satellite azimuth and elevation
        satPosition.calculateAzimuthElevation(satinfo, svid, satinfo.lastpos)

        # calculate the satellite clock correction
        sat_clock_error = rangeCorrection.sv_clock_correction(satinfo, svid, transmitTime, Trel)

        # calculate the ionospheric range correction
        ion_corr = rangeCorrection.ionospheric_correction(satinfo, svid, transmitTime, satinfo.lastpos)

        # calculate the tropospheric range correction
        tropo_corr = rangeCorrection.tropospheric_correction_standard(satinfo, svid)

        # get total range correction
        total_range_correction = ion_corr + tropo_corr

        # correct the pseudo-range for the clock and atmospheric errors
        prCorrected = prMes + sat_clock_error*util.speedOfLight - total_range_correction

        # save the values in the satinfo object
        satinfo.prMeasured[svid] = prMes
        satinfo.prCorrected[svid] = prCorrected
        satinfo.ionospheric_correction[svid] = ion_corr
        satinfo.tropospheric_correction[svid] = tropo_corr
        satinfo.satellite_clock_error[svid] = sat_clock_error

    # if we got at least 4 satellites then calculate a position
    if len(satinfo.satpos) < 4:
        return None

    posestimate = positionLeastSquares(satinfo)
    return posestimate