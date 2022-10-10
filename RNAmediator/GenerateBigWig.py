#!/usr/bin/env python3
### GenerateBigWig.py ---

######################################################################
##
## This program is free software: you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation, either version 3 of the License, or (at
## your option) any later version.
##
## This program is distributed in the hope that it will be useful, but
## WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
## General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with GNU Emacs.  If not, see <http://www.gnu.org/licenses/>.
##
######################################################################
##
### Code:
### IMPORTS

# Logging
import datetime
import glob

# multiprocessing
import multiprocessing

# numpy
import numpy as np
import shlex
from itertools import repeat

# others
from natsort import natsorted
from pandas import Int32Dtype
import pyBigWig as pbw

from RNAmediator.Tweaks.logger import (
    makelogdir,
    makelogfile,
    listener_process,
    listener_configurer,
    worker_configurer,
)
from RNAmediator import _version

__version__ = _version.get_versions()["version"]


# load own modules
from RNAmediator.Tweaks.FileProcessor import *
from RNAmediator.Tweaks.RNAtweaks import *
from RNAmediator.Tweaks.RNAtweaks import _pl_to_array
from RNAmediator.Tweaks.NPtweaks import *

log = logging.getLogger(__name__)  # use module name
SCRIPTNAME = os.path.basename(__file__).replace(".py", "")


def starmap_with_kwargs(pool, fn, args_iter, kwargs_iter):
    """Adds kwargs to starmap

    Parameters
    ----------
    pool : multiprocessing.Pool
        Worker Pool
    fn : function
        Funktion to call
    args_iter : arguments
        Arguments for function
    kwargs_iter : keyword-arguments
        Keyword arguments for function

    Returns
    -------
    multiprocessing.Pool
        Worker Pool starmap with args and kwargs
    """
    args_for_starmap = zip(repeat(fn), args_iter, kwargs_iter)
    return pool.starmap(apply_args_and_kwargs, args_for_starmap)


def apply_args_and_kwargs(fn, args, kwargs):
    """Applies args and kwargs

    Parameters
    ----------
    fn : function
        Function
    args : args
        Arguments for function
    kwargs : keyword-arguments
        Keyword arguments for function

    Returns
    -------
    Function
        Function with variable number of args and kwargs
    """
    return fn(*args, **kwargs)


def scan_input(
    queue,
    configurer,
    level,
    pat,
    cutoff,
    border,
    ulim,
    temperature,
    procs,
    unconstrained,
    unp,
    pai,
    outdir,
    indir,
    genes,
    chromsizes,
    padding,
    chromstr,
):
    """Scan input for files of interest

    Parameters
    ----------
    queue : Multiprocessing.Queue
        Queue used for logging process
    configurer : Function
        Function to configure logging
    level : str
        Loglevel
    pat : str
        Pattern for and window and span, e.g. 30,250. Window can contain other strings for filtering, e.g. Seq1_30
    cutoff : float
        Cutoff for the definition of pairedness, if set to < 1 it will select only constraint regions with mean raw (unconstrained) probability of being unpaired <= cutoff for further processing(default: 1.0)
    border : float
        Cutoff for the minimum change between unconstrained and constraint structure, regions below this cutoff will not be further evaluated.
    ulim : int
        Stretch of nucleotides used during plfold run (-u option)
    temperature : float
        Temperature for structure prediction
    procs : int
        Number of parallel processes to run this job with
    unconstrained : str
        Name for unconstrained provided at ConstraintPLFold -r
    unp : bool
        If unpaired files should be converted as well
    pai : bool
        If paired files should be converted as well
    outdir : str
        Directory to write to
    indir : str
        Directory to read from
    genes : str
        Genomic coordinates bed for genes in standard BED format
    chromsizes : str
        Chromosome sizes file
    padding : int
        Padding around constraint that will be excluded from report, default is 1, so directly overlapping effects will be ignored
    """
    logid = SCRIPTNAME + ".scan_input: "
    try:
        # set path for output
        if outdir:
            log.info(logid + "Printing to " + outdir)
            if not os.path.isabs(outdir):
                outdir = os.path.abspath(outdir)
            if not os.path.exists(outdir):
                os.makedirs(outdir)
        else:
            outdir = os.path.abspath(os.getcwd())

        pattern = pat.split(sep=",")
        window = int(pattern[0])
        span = int(pattern[1])

        genecoords = parse_annotation_bed_by_coordinates(
            genes
        )  # get genomic coords to print to bed later, should always be just one set of coords per gene

        log.debug(f"{logid} COORDINATES: {genecoords}")

        # Create process pool with processes
        num_processes = procs or 1
        call_list = []

        header = read_chromsize(chromsizes)
        rawbigfw = rawbigre = unpbigfw = unpbigre = paibigfw = paibigre = None

        filepaths = [
            os.path.join(outdir, f"{unconstrained}_{ulim}.fw.bw"),
            os.path.join(outdir, f"{unconstrained}_{ulim}.re.bw"),
            os.path.join(outdir, f"{unp}_{ulim}.fw.bw"),
            os.path.join(outdir, f"{unp}_{ulim}.re.bw"),
            os.path.join(outdir, f"{pai}_{ulim}.fw.bw"),
            os.path.join(outdir, f"{pai}_{ulim}.re.bw"),
        ]  # need to save that to get rid of empty files later on

        if unconstrained:
            rawbigfw = pbw.open(filepaths[0], "w")
            rawbigfw.addHeader(header, maxZooms=10)
            rawbigre = pbw.open(filepaths[1], "w")
            rawbigre.addHeader(header, maxZooms=10)
        if unp:
            unpbigfw = pbw.open(filepaths[2], "w")
            unpbigfw.addHeader(header, maxZooms=10)
            unpbigre = pbw.open(filepaths[3], "w")
            unpbigre.addHeader(header, maxZooms=10)
        if pai:
            paibigfw = pbw.open(filepaths[4], "w")
            paibigfw.addHeader(header, maxZooms=10)
            paibigre = pbw.open(filepaths[5], "w")
            paibigre.addHeader(header, maxZooms=10)

        bwlist = [rawbigfw, rawbigre, unpbigfw, unpbigre, paibigfw, paibigre]

        for goi in genecoords:
            log.info(logid + "Working on " + goi)
            chrom, gs, ge, gstrand, _ = get_location_withchrom(genecoords[goi][0], chromstr)

            raw = getfiles(unconstrained, window, span, temperature, goi, indir)
            unpaired = getfiles("diffnu", window, span, temperature, goi, indir)
            paired = getfiles("diffnp", window, span, temperature, goi, indir)

            filelist = equalize_lists([raw, unpaired, paired], goi)

            call_list.append(
                (goi, filelist, chrom, gs, ge, gstrand, ulim, cutoff, border, outdir, padding, chromstr),
            )

        with multiprocessing.Pool(num_processes, maxtasksperchild=1) as pool:
            outlist = starmap_with_kwargs(
                pool,
                generate_bws,
                call_list,
                repeat(
                    {
                        "queue": queue,
                        "configurer": configurer,
                        "level": level,
                    },
                    len(call_list),
                ),
            )
            pool.close()
            pool.join()
        # outlist = sortout(outlist)
        writebws(outlist, bwlist, filepaths)

    except Exception:
        exc_type, exc_value, exc_tb = sys.exc_info()
        tbe = tb.TracebackException(
            exc_type,
            exc_value,
            exc_tb,
        )
        log.error(logid + "".join(tbe.format()))


def generate_bws(
    goi,
    filelist,
    chrom,
    gs,
    ge,
    gstrand,
    ulim,
    cutoff,
    border,
    outdir,
    padding,
    chromstr,
    queue=None,
    configurer=None,
    level=None,
):
    """Generate BigWig entries

    Parameters
    ----------
    filelist : list
        List of files to work on
    chrom: str
        Chromosome
    gs: int
        Start coordinate of gene
    ge: int
        End coordinate of gene
    gstrand: str
        Strand of gene
    ulim : int
        Stretch of nucleotides used during plfold run (-u option)
    cutoff : float
        Cutoff for the definition of pairedness, if set to < 1 it will select only constraint regions with mean raw (unconstrained) probability of being unpaired <= cutoff for further processing(default: 1.0)
    border : float
        Cutoff for the minimum change between unconstrained and constraint structure, regions below this cutoff will not be further evaluated.
    outdir : str
        Directory to write to
    padding : int
        Padding around constraint that will be excluded from report, default is 1, so directly overlapping effects will be ignored
    queue : Multiprocessing.Queue, optional
        Queue used for logging process
    configurer : Function, optional
        Function to configure logging
    level : str, optional
        Loglevel
    """
    logid = SCRIPTNAME + ".judge_diff: "
    try:
        if queue and level:
            configurer(queue, level)

        raw, up, pa = filelist
        out = list()

        if raw:
            for i in range(len(raw)):
                out.append(create_bw_entries(raw[i], goi, gstrand, gs, ge, cutoff, border, ulim, padding, chromstr))
        elif up:
            for i in range(len(up)):
                out.append(create_bw_entries(up[i], goi, gstrand, gs, ge, cutoff, border, ulim, padding, chromstr))
        elif pa:
            for i in range(len(pa)):
                out.append(create_bw_entries(pa[i], goi, gstrand, gs, ge, cutoff, border, ulim, padding, chromstr))
        return out

    except Exception:
        exc_type, exc_value, exc_tb = sys.exc_info()
        tbe = tb.TracebackException(
            exc_type,
            exc_value,
            exc_tb,
        )
        log.error(logid + "".join(tbe.format()))


def sortout(outlist):
    """Sort List of nested dicts

    Parameters
    ----------
    outlist : list
        List of nested dicts with coordinates
    """
    logid = SCRIPTNAME + ".sortout: "

    try:
        tmp = list()
        for entry in outlist:
            tmpent = rec_dd()
            for out in entry:
                log.debug(logid + f"out: {out}")
                for t in ["raw", ["uc"], ["pc"]]:
                    for o in ["fw", "re"]:
                        if len(out[t][o]["chrom"]) > 0:
                            ind = np.argsort(out[t][o]["chr"])
                            tmpent[t][o]["chrom"] = np.empty(1, np.str)
                            for f in ["start", "end", "values"]:
                                tmpent[t][o][f] = np.empty(1, np.int64)
                            for i in ind:
                                for f in ["chrom", "start", "end", "values"]:
                                    tmpent[t][o][f].append(out[t][o][f][i])
            tmp.append(tmpent)
        return tmp

    except Exception:
        exc_type, exc_value, exc_tb = sys.exc_info()
        tbe = tb.TracebackException(
            exc_type,
            exc_value,
            exc_tb,
        )
        log.error(logid + "".join(tbe.format()))

    return outlist


def writebws(outlist, listofbws, filepaths):
    """Write BigWig entries to file

    Parameters
    ----------
    outlist : Nested defaultdict
        BigWig entries
    listofbws : list
        List of BigWig filehandles
    filepaths : list
        List of BigWig file paths for cleanup of empty files
    """
    logid = SCRIPTNAME + ".writebws: "

    try:
        log.debug(logid + f"bwlist:{listofbws}")
        for entry in outlist:
            for out in entry:
                log.debug(logid + f"out: {out}")
                if len(out["raw"]["fw"]["chrom"]) > 0:
                    listofbws[0].addEntries(
                        out["raw"]["fw"]["chrom"],
                        out["raw"]["fw"]["start"],
                        ends=out["raw"]["fw"]["end"],
                        values=out["raw"]["fw"]["value"],
                        validate=False,
                    )
                if len(out["raw"]["re"]["chrom"]) > 0:
                    listofbws[1].addEntries(
                        out["raw"]["re"]["chrom"],
                        out["raw"]["re"]["start"],
                        ends=out["raw"]["re"]["end"],
                        values=out["raw"]["re"]["value"],
                        validate=False,
                    )
                if len(out["uc"]["fw"]["chrom"]) > 0:
                    listofbws[2].addEntries(
                        out["uc"]["fw"]["chrom"],
                        out["uc"]["fw"]["start"],
                        ends=out["uc"]["fw"]["end"],
                        values=out["uc"]["fw"]["value"],
                        validate=False,
                    )
                if len(out["uc"]["re"]["chrom"]) > 0:
                    listofbws[3].addEntries(
                        out["uc"]["re"]["chrom"],
                        out["uc"]["re"]["start"],
                        ends=out["uc"]["re"]["end"],
                        values=out["uc"]["re"]["value"],
                        validate=False,
                    )
                if len(out["pc"]["fw"]["chrom"]) > 0:
                    listofbws[4].addEntries(
                        out["pc"]["fw"]["chrom"],
                        out["pc"]["fw"]["start"],
                        ends=out["pc"]["fw"]["end"],
                        values=out["pc"]["fw"]["value"],
                        validate=False,
                    )
                if len(out["pc"]["re"]["chrom"]) > 0:
                    listofbws[5].addEntries(
                        out["pc"]["re"]["chrom"],
                        out["pc"]["re"]["start"],
                        ends=out["pc"]["re"]["end"],
                        values=out["pc"]["re"]["value"],
                        validate=False,
                    )
        log.debug(logid + f"bwlist_after:{listofbws}")
        for i in range(len(listofbws)):
            bw = listofbws[i]
            if bw:
                bw.close()
                bw = pbw.open(filepaths[i], "r")
                if bw.header()["nBasesCovered"] != 0:
                    log.info(logid + f"{bw} is valid: {bw.isBigWig()}")
                    bw.close()
                else:
                    bw.close()
                    os.remove(filepaths[i])
                    log.warning(logid + f"File {bw} is empty, was deleted.")

    except Exception:
        exc_type, exc_value, exc_tb = sys.exc_info()
        tbe = tb.TracebackException(
            exc_type,
            exc_value,
            exc_tb,
        )
        log.error(logid + "".join(tbe.format()))


def getfiles(name, window, span, temperature, goi, indir=None):
    """Retrieve files following specified pattern

    Parameters
    ----------
    name : str
        Name of file to search for, e.g. 'raw', 'unpaired' or 'paired'
    window : int
        size of folding window used
    span : int
        length of basepair span used
    temperature : float
        temperature used for folding
    goi : str
        Gene of interest
    indir : str, optional
        Path to directory of interest (default is None)

    Returns
    -------
    List
        List of files found folowing search pattern
    """
    logid = SCRIPTNAME + ".getfiles: "
    ret = list()
    if not name:
        return None
    else:
        # get files with specified pattern
        temperature = re.sub("[.,]", "", str(temperature))
        lookfor = os.path.abspath(
            os.path.join(
                indir,
                goi,
                f"*{goi}*_{name}_*{str(window)}_{str(span)}_{str(temperature)}.npy",
            )
        )
        log.debug(logid + f"LOOKFOR: {lookfor}")
        collectall = natsorted(glob.glob(lookfor), key=lambda y: y.lower())
        # get absolute path for files
        fullname = [os.path.abspath(i) for i in collectall]
        log.debug(logid + f"PATHS: {fullname}")

        if not fullname and not "diff" in name:
            log.warning(
                logid
                + "Could not find files for Gene "
                + str(goi)
                + " and window "
                + str(window)
                + " and span "
                + str(span)
                + " and temperature "
                + str(temperature)
                + " Will skip"
            )
            return list()
        else:
            return fullname


def read_chromsize(cs, limit=32):
    """Read chromosome sizes from file

    Parameters
    ----------
    cs : str
        File to read from
    limit: int
        Max length for chrom names, only 32 characters allowed by ucsc

    Returns
    -------
    sizes: list(tuple(str,int))
        List of tuples with chromosome name and size
    """
    logid = SCRIPTNAME + ".read_chromsize: "
    sizes = list()
    if ".gzip" in os.path.basename(cs)[-6:]:
        sizes = gzip.open(cs, "rt").read().splitlines()
    else:
        sizes = open(cs, "r").read().splitlines()
    sizes = [tuple((str(x), int(y))) for x, y in [l.split("\t") for l in sizes]]
    for i in range(len(sizes)):
        l = list(sizes[i])
        if l[0][:2] != "chr":  # UCSC needs chr in chromname
            if l[0][:2] == "CHR":
                l[0] = "chr" + l[3:]
            else:
                l[0] = "chr" + l[0]
        if len(l[0]) > limit:  # UCSC only allows 32char lenght strings
            l[0] = l[0][:limit]
        sizes[i] = tuple(l)
    log.debug(f"{logid} {sizes}")
    return sizes


def equalize_lists(listoflists, id=None):
    logid = f"{SCRIPTNAME}.equalize_lists: "
    log.debug(f"{logid} {listoflists}")
    if all([len(x) == 0 for x in listoflists]):
        log.warning(f"No files found for {id}, skipping!")
    max_length = 0
    for list in listoflists:
        max_length = max(max_length, len(list))
    for list in listoflists:
        list += [None] * (max_length - len(list))
    return listoflists


def create_bw_entries(fname, goi, gstrand, gs, ge, cutoff, border, ulim, padding, chromstr):
    """Create entries for BigWig files

    Parameters
    ----------
    fname : str
        Filename to read from
    goi : str
        Gene of interest
    gstrand : str
        strand of goi
    gs: int
        gene start coordinates
    ge: int
        gene end coordinates
    cutoff : float
        Cutoff for the definition of pairedness, if set to < 1 it will select only constraint regions with mean raw (unconstrained) probability of being unpaired <= cutoff for further processing(default: 1.0)
    border : float
        Cutoff for the minimum change between unconstrained and constraint structure, regions below this cutoff will not be further evaluated.
    ulim : int
        Stretch of nucleotides used during plfold run (-u option)
    padding : int
        Padding around constraint that will be excluded from report, default is 1, so directly overlapping effects will be ignored

    Returns
    -------
    _type_
        _description_

    Raises
    ------
    Exception
        _description_
    """
    try:
        logid = SCRIPTNAME + ".create_bw_entries: "
        log.debug(logid + f"{fname}")
        if "diff" in fname:
            repl = "StruCons_" + str(goi)
            log.debug(logid + f'{str(os.path.basename(fname).replace(repl + "_", "", 1))}')
            chrom, strand, cons, reg, f, window, span, temperature = map(
                str, str(os.path.basename(fname)).replace(repl + "_", "", 1).split(sep="_")
            )

        else:
            repl = str(goi)
            reg = "0-0"
            log.debug(logid + f'{str(os.path.basename(fname).replace(repl + "_", "", 1).split(sep="_"))}')
            chrom, strand, cons, f, window, span, temperature = map(
                str, str(os.path.basename(fname)).replace(repl + "_", "", 1).split(sep="_")
            )

        if chrom[:2] != "chr":  # UCSC needs chr in chromname
            if chrom[:2] == "CHR":
                chrom = "chr" + chrom[3:]
            else:
                chrom = "chr" + chrom

        temperature = temperature.replace(".npy", "")
        span = span.split(sep=".")[0]
        cs, ce = map(int, cons.split(sep="-"))
        ws, we = map(int, reg.split(sep="-"))

        cs = cs - ws  # fit to window and make 0-based
        ce = ce - ws  # fit to window and make 0-based closed

        if 0 > any([cs, ce, ws, we]):
            raise Exception(
                "One of "
                + str([cs, ce, ws, we])
                + " lower than 0! this should not happen for "
                + ",".join([goi, chrom, strand, cons, reg, f, window, span, temperature])
            )

        if gstrand != "-":
            ws = ws + gs - 2  # get genomic coords 0 based closed, ws and gs are 1 based
            we = we + gs - 2

        else:
            wst = ws  # temp ws for we calc
            ws = ge - we  # get genomic coords 0 based closed, ge and we are 1 based
            we = ge - wst

        log.debug(
            logid
            + "Coords: "
            + " ".join(
                map(
                    str,
                    [
                        goi,
                        chrom,
                        gstrand,
                        cons,
                        reg,
                        f,
                        window,
                        span,
                        temperature,
                        gs,
                        ge,
                        cs,
                        ce,
                        ws,
                        we,
                    ],
                )
            )
        )

        border = abs(border)  # defines how big a diff has to be to be of importance

        log.info(
            logid
            + "Continuing "
            + str(goi)
            + " calculation with cutoff: "
            + str(cutoff)
            + " and border "
            + str(border)
        )  # + ' and ' + str(border2))

        # Read in plfold output
        if not "diff" in fname:
            noc = _pl_to_array(fname, ulim)
        else:
            uncons = str(fname).replace("diffnu_", "").replace("diffnp_", "")
            fn = str.split("_", uncons)
            fn[3] = "raw"
            uncons = str.join("_", fn)
            noc = _pl_to_array(uncons, ulim)

        out = rec_dd()

        log.debug(logid + f"out: {out}, noc: {noc[1:10]}, cs: {cs}, ce: {ce}, cutoff: {cutoff}")

        if "diff" in fname and abs(np.nanmean(noc[cs : ce + 1])) <= cutoff:
            if "diffnu" in fname or "diffnp" in fname:
                oc = _pl_to_array(fname, ulim)  # This is the diffacc for unpaired constraint

            # Calculate raw prop unpaired for constraint diff file
            oc = noc + oc
        else:
            oc = None
        """
        Collect positions of interest with padding around constraint
        Constraints are influencing close by positions strongest so strong influence of binding there is expected
        """

        chroms = defaultdict(list)
        starts = defaultdict(list)
        ends = defaultdict(list)
        values = defaultdict(list)

        for pos in range(len(noc)):
            # if pos not in range(cs - padding + 1 - ulim, ce + padding + 1 + ulim):
            if gstrand != "-":
                gpos = pos + ws - ulim + 1  # already 0-based
                gend = gpos + 1  # 0-based half-open
                orient = "fw"
            else:
                gpos = we - pos  # already 0-based
                gend = gpos + 1  # 0-based half-open
                orient = "re"

            log.debug(
                logid
                + f"chrom: {chrom}, gpos: {gpos}, gend: {gend}, strand: {orient}, position: {pos}, noc: {noc[pos]}, border: {border}"
            )

            if border < abs(noc[pos]) and not np.isnan(noc[pos]):
                chroms["raw"].append(chrom)
                starts["raw"].append(gpos)
                ends["raw"].append(gend)
                values["raw"].append(noc[pos])

            if oc and "diffnu" in fname and border < abs(oc[pos]) and not np.isnan(oc[pos]):
                chroms["uc"].append(chrom)
                starts["uc"].append(gpos)
                ends["uc"].append(gend)
                values["uc"].append(oc[pos])

            if oc and "diffnp" in fname and border < abs(oc[pos]) and not np.isnan(oc[pos]):
                chroms["pc"].append(chrom)
                starts["pc"].append(gpos)
                ends["pc"].append(gend)
                values["pc"].append(oc[pos])

        for t in ["raw", "uc", "pc"]:
            out = fill_array(out, t, orient, chroms, starts, ends, values)

        return out

    except Exception:
        exc_type, exc_value, exc_tb = sys.exc_info()
        tbe = tb.TracebackException(
            exc_type,
            exc_value,
            exc_tb,
        )
        log.error(logid + "".join(tbe.format()))


def rec_dd():
    return defaultdict(rec_dd)


def fill_array(out, which, orient, chroms, starts, ends, values):
    try:
        logid = f"{SCRIPTNAME}.fill_array: "
        log.debug(f"{logid} {which}-{orient}:{chroms}:{starts}-{ends}:{values}")
        out[which][orient]["chrom"] = np.array(chroms[which], np.str)
        out[which][orient]["start"] = np.array(starts[which], np.int64)
        out[which][orient]["end"] = np.array(ends[which], np.int64)
        out[which][orient]["value"] = np.array(values[which], np.float64)
        return out

    except Exception:
        exc_type, exc_value, exc_tb = sys.exc_info()
        tbe = tb.TracebackException(
            exc_type,
            exc_value,
            exc_tb,
        )
        log.error(logid + "".join(tbe.format()))


def main(args=None):
    """Main process, prepares run_settings dict, creates logging process queue and worker processes for folding, calls screen_genes

    Parameters
    ----------

    Returns
    -------
    Call to scan_input
    """

    logid = SCRIPTNAME + ".main: "

    try:
        if not args:
            args = parseargs_browser()

        if args.version:
            sys.exit("Running RNAmediator version " + __version__)

        #  Logging configuration
        logdir = args.logdir
        ts = str(datetime.datetime.now().strftime("%Y%m%d_%H_%M_%S_%f"))
        logfile = str.join(os.sep, [os.path.abspath(logdir), SCRIPTNAME + "_" + ts + ".log"])
        loglevel = args.loglevel

        makelogdir(logdir)
        makelogfile(logfile)

        queue = multiprocessing.Manager().Queue(-1)
        listener = multiprocessing.Process(
            target=listener_process,
            args=(queue, listener_configurer, logfile, loglevel),
        )
        listener.start()

        worker_configurer(queue, loglevel)

        log.info(logid + "Running " + SCRIPTNAME + " on " + str(args.procs) + " cores.")
        log.info(logid + "CLI: " + sys.argv[0] + " " + "{}".format(" ".join([shlex.quote(s) for s in sys.argv[1:]])))

        scan_input(
            queue,
            worker_configurer,
            loglevel,
            args.pattern,
            args.cutoff,
            args.border,
            args.ulimit,
            args.temperature,
            args.procs,
            args.unconstrained,
            args.unpaired,
            args.paired,
            args.outdir,
            args.dir,
            args.genes,
            args.chromsizes,
            args.padding,
            args.chromstr,
        )

        queue.put_nowait(None)
        listener.join()

    except Exception:
        exc_type, exc_value, exc_tb = sys.exc_info()
        tbe = tb.TracebackException(
            exc_type,
            exc_value,
            exc_tb,
        )
        log.error(logid + "".join(tbe.format()))


####################
####    MAIN    ####
####################
if __name__ == "__main__":

    logid = SCRIPTNAME + ".main: "
    try:
        main()

    except Exception:
        exc_type, exc_value, exc_tb = sys.exc_info()
        tbe = tb.TracebackException(
            exc_type,
            exc_value,
            exc_tb,
        )
        log.error(logid + "".join(tbe.format()))

######################################################################
### GenerateBigWig.py ends here
