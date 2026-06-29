# encoding: utf-8

###########################################################################################################
#
# Ultimate Measure
#
# A Reporter plugin for Glyphs 3. Toggle it on in the View menu; it then draws
# only while you HOLD Option (Alt), in one of two modes depending on selection:
#
#   NOTHING SELECTED — stem ruler under the cursor
#     Option            measure the nearest stem / edges under the cursor
#     Option + Shift    full slice: every gap across the outline along the ray
#
#   A NODE SELECTED — Figma-style X/Y to the hovered point
#     Option            show the horizontal (blue) and vertical (tan) distance
#                       from the selected node to whatever node or handle the
#                       cursor is over (within ~10 px)
#
#   Option + Command    hidden (that combo is Glyphs' zoom gesture)
#
# Stem rulers: pink tags on ink, grey on counters. Measurement logic is a Python
# port of "Show Stem Thickness" by Rafal Buchner, with code samples by Georg
# Seifert, Rainer Scheichelbauer and Mark Frömberg.
# https://github.com/RafalBuchner/StemThickness  (Apache License 2.0)
#
###########################################################################################################

from __future__ import division, print_function, unicode_literals
import math
import time
import objc
from GlyphsApp import Glyphs
from GlyphsApp.plugins import ReporterPlugin
from AppKit import (
    NSColor, NSPoint, NSBezierPath, NSApplication,
    NSAttributedString, NSFont, NSGraphicsContext, NSAffineTransform,
)

try:
    from Foundation import NSTimer
except Exception:
    NSTimer = None
try:
    from Quartz import CGContextSetAlpha
except Exception:
    CGContextSetAlpha = None

try:
    from GlyphsApp import OFFCURVE
except ImportError:
    OFFCURVE = "offcurve"

try:
    from GlyphsApp import GSNode
except ImportError:
    GSNode = None


def _const(name, fallback):
    try:
        import AppKit
        return getattr(AppKit, name)
    except (ImportError, AttributeError):
        return fallback

OPTION_MASK = _const("NSEventModifierFlagOption", 1 << 19)
COMMAND_MASK = _const("NSEventModifierFlagCommand", 1 << 20)
SHIFT_MASK = _const("NSEventModifierFlagShift", 1 << 17)

NSEventMaskMouseMoved = _const("NSEventMaskMouseMoved", 1 << 5)
NSEventMaskFlagsChanged = _const("NSEventMaskFlagsChanged", 1 << 12)
NSEventTypeFlagsChanged = _const("NSEventTypeFlagsChanged", 12)
NSFontWeightMedium = _const("NSFontWeightMedium", 0.23)
NSFontAttributeName = _const("NSFontAttributeName", "NSFont")
NSForegroundColorAttributeName = _const("NSForegroundColorAttributeName", "NSColor")

try:
    from AppKit import NSEvent
except ImportError:
    NSEvent = None

# --- tunables (all in screen pixels) --------------------------------------
SNAP_PX = 10.0      # snap the stem-ruler origin to an on-curve node within this
CATCH_PX = 10.0     # selection mode: catch a node/handle within this of cursor
DOT_PX = 8.0        # endpoint dot diameter (uniform)
TAG_H = 16.0        # tag height
TAG_PAD = 6.0       # tag left/right padding
TAG_RADIUS = 4.0    # tag corner radius
TAG_FONT = 12.0     # tag text size
TAG_TEXT_DY = 0.0   # optional manual nudge on top of metric centring (+ = up)
MAX_SPAN = 2000.0   # ignore stem spans longer than this (em units)
MIN_LEG = 0.5       # don't draw an X/Y leg shorter than this (em units)
CORNER_TURN_DEG = 20.0  # snapped node sharper than this -> treat as a corner (X/Y)
VERTEX_TOL_PX = 3.0  # if the nearest outline point is this close to a vertex, snap to it
FADE_SEC = 0.1      # fade-in duration when the measurement appears (0 = instant)


def _distance(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def _unit_vector(frm, to):
    dx = to.x - frm.x
    dy = to.y - frm.y
    length = math.hypot(dx, dy)
    if length == 0:
        return NSPoint(0, 0)
    return NSPoint(dx / length, dy / length)


def _to_point(value):
    """Intersection results may be NSValue-wrapped points or plain NSPoints."""
    if hasattr(value, "pointValue"):
        return value.pointValue()
    return NSPoint(value.x, value.y)


def _format_distance(d, scale):
    if scale < 2:
        return "%d" % round(d)
    elif scale < 3:
        return "%0.1f" % d
    elif scale < 10:
        return "%0.2f" % d
    return "%0.3f" % d


class UltimateMeasure(ReporterPlugin):

    @objc.python_method
    def settings(self):
        self.menuName = Glyphs.localize({
            'en': 'Ultimate Measure',
            'de': 'Ultimate Measure',
        })
        # Stem ruler: pink on ink, grey on counters; white text. Grey dots.
        self.stemColor = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.0, 200 / 255.0, 1.0)
        self.counterColor = NSColor.colorWithCalibratedRed_green_blue_alpha_(151 / 255.0, 166 / 255.0, 177 / 255.0, 1.0)
        self.stemTextColor = NSColor.whiteColor()
        self.counterTextColor = NSColor.whiteColor()
        self.dotColor = NSColor.colorWithCalibratedWhite_alpha_(117 / 255.0, 1.0)  # 757575
        # Selection mode: horizontal distances blue, vertical distances tan.
        self.xColor = NSColor.colorWithCalibratedRed_green_blue_alpha_(0 / 255.0, 59 / 255.0, 255 / 255.0, 1.0)
        self.yColor = NSColor.colorWithCalibratedRed_green_blue_alpha_(128 / 255.0, 0 / 255.0, 255 / 255.0, 1.0)
        self.whiteText = NSColor.whiteColor()
        self._tagFont = None

    @objc.python_method
    def start(self):
        # Live tracking: a local event monitor forces a redraw on every mouse
        # move and modifier change, and captures the cursor from real events so
        # foreground never reads a stale location during an unrelated redraw.
        self._eventMonitor = None
        self._mouseLoc = None
        self._unionLayer = None   # cached overlap-removed copy
        self._unionKey = None
        # fade-in state
        self._appearTime = None
        self._wasShowing = False
        self._didDraw = False
        self._fadeTimer = None
        if NSEvent is None:
            return
        try:
            mask = NSEventMaskMouseMoved | NSEventMaskFlagsChanged
            self._eventMonitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                mask, self.liveRedraw)
        except Exception as e:
            print("UltimateMeasure: could not start event monitor:", e)

    @objc.python_method
    def liveRedraw(self, event):
        try:
            self.captureMouse(event)
            if event.type() == NSEventTypeFlagsChanged or self.optionIsHeld():
                Glyphs.redraw()
        except Exception:
            pass
        return event

    @objc.python_method
    def captureMouse(self, event):
        try:
            if self.controller is None:
                return
            view = self.controller.graphicView()
            win = view.window()
            # Keep mouse-moved delivery armed; macOS/Glyphs can reset this, which
            # otherwise freezes live tracking until the next click or Option press.
            if win is not None:
                win.setAcceptsMouseMovedEvents_(True)
            # A modifier change (Option press) carries no reliable location, and
            # the cursor hasn't moved anyway — keep the last real mouse position.
            if event.type() == NSEventTypeFlagsChanged:
                return
            if event.window() is not None and event.window() == win:
                self._mouseLoc = view.getActiveLocation_(event)
        except Exception:
            pass

    # ----- modifier state ------------------------------------------------

    @objc.python_method
    def _flags(self):
        if NSEvent is not None:
            return NSEvent.modifierFlags()
        event = NSApplication.sharedApplication().currentEvent()
        return event.modifierFlags() if event else 0

    @objc.python_method
    def optionIsHeld(self):
        return bool(self._flags() & OPTION_MASK)

    @objc.python_method
    def commandIsHeld(self):
        return bool(self._flags() & COMMAND_MASK)

    @objc.python_method
    def shiftIsHeld(self):
        return bool(self._flags() & SHIFT_MASK)

    # ----- geometry ------------------------------------------------------

    @objc.python_method
    def mousePositionInGlyph(self):
        """Cursor position in glyph coords, from the monitor's captured value."""
        if self._mouseLoc is not None:
            return self._mouseLoc
        try:
            view = self.controller.graphicView()
            event = NSApplication.sharedApplication().currentEvent()
            return view.getActiveLocation_(event)
        except Exception:
            return None

    @objc.python_method
    def selectedAnchor(self, layer):
        """Position of the single selected point to anchor from, or None.

        Accepts a real on-curve/handle node (GSNode) AND a GSHandle — the latter
        is what Glyphs hands back when you select a 'future' point created by an
        overlap intersection or a stroke expansion. Several selected -> None
        (fall back to the free stem ruler)."""
        pts = []
        for obj in layer.selection:
            if type(obj).__name__ in ("GSNode", "GSHandle"):
                try:
                    p = obj.position
                    pts.append(NSPoint(p.x, p.y))
                except Exception:
                    pass
            if len(pts) > 1:
                return None
        return pts[0] if len(pts) == 1 else None

    @objc.python_method
    def workingLayer(self, layer):
        """The visible outline to measure: a decomposed copy with strokes expanded
        and overlaps removed, so stroked (unexpanded) glyphs measure as their real
        filled shape and every expanded corner / crossing is a real node. Cached;
        rebuilt only when the outline changes."""
        try:
            sig, cnt = 0.0, 0
            for path in layer.paths:
                for node in path.nodes:
                    sig += node.position.x * 2.7 + node.position.y * 3.1
                    cnt += 1
                # stroke width/height changes don't move nodes — fold them in.
                try:
                    a = path.attributes
                    sig += (a.get("strokeWidth", 0) or 0) * 0.9
                    sig += (a.get("strokeHeight", 0) or 0) * 1.1
                except Exception:
                    pass
            for comp in layer.components:
                cnt += 1
                try:
                    sig += comp.position.x * 1.3 + comp.position.y * 1.7
                except Exception:
                    pass
            key = (id(layer), cnt, round(sig, 1))
            if self._unionKey == key and self._unionLayer is not None:
                return self._unionLayer
            copy = layer.copyDecomposedLayer()
            try:
                copy.flattenOutlines()  # expand strokes / corner components to outlines
            except Exception:
                pass                    # older Glyphs without the method: skip
            copy.removeOverlap()
            self._unionLayer, self._unionKey = copy, key
            return copy
        except Exception:
            return layer

    @objc.python_method
    def nearestTargetPoint(self, layer, work, cursor, scale, excludePos):
        """Nearest catchable point within the catch radius: any node or handle on
        the original layer, plus the union outline's on-curve nodes (which sit at
        overlap crossings). Returns an NSPoint or None."""
        catch = CATCH_PX / scale
        best, bestD = None, catch

        for path in layer.paths:
            for node in path.nodes:
                p = node.position
                if excludePos is not None and _distance(p, excludePos) < 0.5:
                    continue
                d = _distance(p, cursor)
                if d < bestD:
                    bestD, best = d, NSPoint(p.x, p.y)

        if work is not None and work is not layer:
            for path in work.paths:
                for node in path.nodes:
                    if node.type == OFFCURVE:
                        continue
                    p = node.position
                    if excludePos is not None and _distance(p, excludePos) < 0.5:
                        continue
                    d = _distance(p, cursor)
                    if d < bestD:
                        bestD, best = d, NSPoint(p.x, p.y)

        return best

    @objc.python_method
    def nodeNormal(self, path, node):
        """Unit normal to the path at an on-curve node, from its neighbours.
        On a smooth curve node the neighbours are the off-curve handles, so this
        is the true curve normal (radial on an O); at a corner it's the bisector."""
        nodes = path.nodes
        n = len(nodes)
        if n < 2:
            return NSPoint(0, 1)
        idx = None
        for j in range(n):
            if nodes[j] == node:
                idx = j
                break
        if idx is None:
            return NSPoint(0, 1)
        prev = nodes[(idx - 1) % n].position
        nxt = nodes[(idx + 1) % n].position
        tangent = _unit_vector(prev, nxt)
        if tangent.x == 0 and tangent.y == 0:
            return NSPoint(0, 1)
        return NSPoint(-tangent.y, tangent.x)

    @objc.python_method
    def findSnapNode(self, layer, pt, scale):
        snap, sn, sp = SNAP_PX / scale, None, None
        for path in layer.paths:
            for node in path.nodes:
                if node.type == OFFCURVE:
                    continue
                d = _distance(node.position, pt)
                if d < snap:
                    snap, sn, sp = d, node, path
        return sn, sp

    @objc.python_method
    def isCornerNode(self, path, node):
        """True for a sharp corner, where a perpendicular normal is ambiguous
        and we should fall back to X/Y. Curve points (off-curve neighbours) and
        roughly straight continuations are not corners."""
        nodes = path.nodes
        n = len(nodes)
        idx = next((j for j in range(n) if nodes[j] == node), None)
        if idx is None:
            return False
        prevN = nodes[(idx - 1) % n]
        nextN = nodes[(idx + 1) % n]
        if prevN.type == OFFCURVE and nextN.type == OFFCURVE:
            return False
        v1 = _unit_vector(prevN.position, node.position)
        v2 = _unit_vector(node.position, nextN.position)
        dot = v1.x * v2.x + v1.y * v2.y
        return dot < math.cos(math.radians(CORNER_TURN_DEG))

    @objc.python_method
    def buildRay(self, layer, pt, snapNode, snapPath):
        """Perpendicular ray: cursor-driven normally; locked to a snapped curve
        node's normal when one is in range."""
        closest, best = None, 1.0e9
        for path in layer.paths:
            try:
                p, _t = path.nearestPointOnPath_pathTime_(pt, None)
            except Exception:
                continue
            d = _distance(p, pt)
            if d < best:
                best, closest = d, p
        if closest is None:
            return None
        if snapNode is not None:
            origin = snapNode.position
            direction = self.nodeNormal(snapPath, snapNode)
        else:
            origin = closest
            direction = _unit_vector(pt, closest)
        if direction.x == 0 and direction.y == 0:
            direction = NSPoint(0, 1)
        rayA = NSPoint(origin.x + direction.x * 10000, origin.y + direction.y * 10000)
        rayB = NSPoint(origin.x - direction.x * 10000, origin.y - direction.y * 10000)
        return origin, rayA, rayB

    @objc.python_method
    def straightNeighbour(self, path, idx, step):
        """The adjacent on-curve node in direction step (+1/-1) ONLY if that
        segment is straight (a line). For a curve segment the immediate
        neighbour is an off-curve handle, so we return None and skip it."""
        nodes = path.nodes
        nb = nodes[(idx + step) % len(nodes)]
        return None if nb.type == OFFCURVE else nb

    # ----- drawing -------------------------------------------------------

    @objc.python_method
    def drawDot(self, point, scale, color, dpx=DOT_PX):
        self._didDraw = True
        color.set()
        d = dpx / scale
        r = d * 0.5
        NSBezierPath.bezierPathWithOvalInRect_(((point.x - r, point.y - r), (d, d))).fill()

    @objc.python_method
    def drawDashedLine(self, a, b, scale, color):
        self._didDraw = True
        color.set()
        bez = NSBezierPath.bezierPath()
        bez.setLineWidth_(1.0 / scale)
        bez.setLineDash_count_phase_([3.0 / scale, 3.0 / scale], 2, 0)
        bez.moveToPoint_(a)
        bez.lineToPoint_(b)
        bez.stroke()

    @objc.python_method
    def drawSolidLine(self, a, b, scale, color):
        self._didDraw = True
        color.set()
        bez = NSBezierPath.bezierPath()
        bez.setLineWidth_(1.0 / scale)
        bez.moveToPoint_(a)
        bez.lineToPoint_(b)
        bez.stroke()

    @objc.python_method
    def tagFont(self):
        # System font — matches Glyphs' own UI labels and renders identically for
        # every user (no dependence on an installed typeface). Monospaced digits
        # so the badges don't jitter in width as the numbers change.
        if self._tagFont is None:
            try:
                self._tagFont = NSFont.monospacedDigitSystemFontOfSize_weight_(TAG_FONT, NSFontWeightMedium)
            except Exception:
                self._tagFont = NSFont.systemFontOfSize_weight_(TAG_FONT, NSFontWeightMedium)
        return self._tagFont

    @objc.python_method
    def drawTag(self, text, center, scale, bgColor, textColor):
        self._didDraw = True
        font = self.tagFont()
        attrs = {
            NSFontAttributeName: font,
            NSForegroundColorAttributeName: textColor,
        }
        astr = NSAttributedString.alloc().initWithString_attributes_(text, attrs)
        tsize = astr.size()
        tagW = tsize.width + 2 * TAG_PAD

        # Local px-sized coordinate system so the tag is constant on screen.
        ctx = NSGraphicsContext.currentContext()
        ctx.saveGraphicsState()
        t = NSAffineTransform.transform()
        t.translateXBy_yBy_(center.x, center.y)
        s = 1.0 / scale
        t.scaleXBy_yBy_(s, s)
        t.concat()
        rect = ((-tagW / 2.0, -TAG_H / 2.0), (tagW, TAG_H))
        bgColor.set()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, TAG_RADIUS, TAG_RADIUS).fill()
        # Centre the digits by the font's own cap-height, not the line box.
        # drawAtPoint's y is the text box bottom; baseline = y - descender, so
        # baseline = descender puts the box bottom right, and we offset up by
        # half the cap-height to centre the figures. Robust across fonts/OS,
        # which differ in line metrics (the cause of the "text too high" bug).
        try:
            baseY = font.descender() - font.capHeight() / 2.0 + TAG_TEXT_DY
        except Exception:
            baseY = -tsize.height / 2.0 + TAG_TEXT_DY
        astr.drawAtPoint_((-tsize.width / 2.0, baseY))
        ctx.restoreGraphicsState()

    # ----- stem ruler (nothing selected) ---------------------------------

    @objc.python_method
    def drawStemRuler(self, layer, scale):
        # `layer` here is the overlap-removed union, so overlap crossings are
        # already real corner nodes and need no special handling.
        pt = self.mousePositionInGlyph()
        if pt is None:
            return
        snapNode, snapPath = self.findSnapNode(layer, pt, scale)
        if snapNode is None:
            # Not within the cursor snap radius of a node, but the cursor may
            # still project onto a vertex (e.g. hovering just outside a corner,
            # or inside between features), which would give a diagonal ray.
            # Detect that and snap to the vertex so its normal / corner logic is
            # used instead of a diagonal cursor->vertex direction.
            closest, cdist = None, 1.0e9
            for path in layer.paths:
                try:
                    p, _t = path.nearestPointOnPath_pathTime_(pt, None)
                except Exception:
                    continue
                d = _distance(p, pt)
                if d < cdist:
                    cdist, closest = d, p
            if closest is not None:
                vn, vnd, vp = None, 1.0e9, None
                for path in layer.paths:
                    for node in path.nodes:
                        if node.type == OFFCURVE:
                            continue
                        d = _distance(node.position, closest)
                        if d < vnd:
                            vnd, vn, vp = d, node, path
                if vn is not None and vnd < VERTEX_TOL_PX / scale:
                    snapNode, snapPath = vn, vp
        if snapNode is not None and self.isCornerNode(snapPath, snapNode):
            self.drawCornerSegments(layer, snapNode, snapPath, scale)
            return
        ray = self.buildRay(layer, pt, snapNode, snapPath)
        if ray is None:
            return
        origin, rayA, rayB = ray
        try:
            crossings = layer.calculateIntersectionsStartPoint_endPoint_decompose_(rayA, rayB, False)
        except AttributeError:
            crossings = layer.intersectionsBetweenPoints(rayA, rayB)
        if not crossings:
            return
        points = [_to_point(v) for v in crossings]
        if len(points) < 2:
            return

        sliceMode = self.shiftIsHeld()
        if sliceMode:
            spans = [(points[i], points[i + 1]) for i in range(len(points) - 1)]
            edgeDots = points
            originDot = None
        else:
            onCurve = origin
            nearestI = min(range(len(points)), key=lambda i: _distance(points[i], onCurve))
            spans, edgeDots, originDot = [], [], onCurve
            if nearestI + 1 < len(points):
                spans.append((onCurve, points[nearestI + 1]))
                edgeDots.append(points[nearestI + 1])
            if nearestI - 1 >= 0:
                spans.append((onCurve, points[nearestI - 1]))
                edgeDots.append(points[nearestI - 1])

        outline = layer.bezierPath
        items = []
        for a, b in spans:
            d = _distance(a, b)
            if not (0.01 < d < MAX_SPAN):
                continue
            mid = NSPoint((a.x + b.x) * 0.5, (a.y + b.y) * 0.5)
            inside = bool(outline and outline.containsPoint_(mid))
            color = self.stemColor if inside else self.counterColor
            items.append((a, b, mid, d, color))

        for a, b, mid, d, color in items:
            self.drawDashedLine(a, b, scale, color)
        for p in edgeDots:
            self.drawDot(p, scale, self.dotColor)
        if originDot is not None:
            self.drawDot(originDot, scale, self.dotColor)
        for a, b, mid, d, color in items:
            self.drawTag(_format_distance(d, scale), mid, scale, color, self.whiteText)

    @objc.python_method
    def drawCornerSegments(self, layer, node, path, scale):
        """At a corner the perpendicular normal is ambiguous, so measure along
        the path instead: from the corner to the adjacent on-curve node in each
        direction, but ONLY where that segment is straight (curve legs are
        skipped — the chord to the next point isn't useful). Each leg is coloured
        by its dominant axis (blue = horizontal, purple = vertical)."""
        nodes = path.nodes
        n = len(nodes)
        idx = next((j for j in range(n) if nodes[j] == node), None)
        o = node.position
        self.drawDot(o, scale, self.dotColor)
        if idx is None:
            return
        for step in (-1, 1):
            nb = self.straightNeighbour(path, idx, step)
            if nb is None:
                continue
            b = nb.position
            d = _distance(o, b)
            if d < MIN_LEG:
                continue
            color = self.xColor if abs(b.x - o.x) >= abs(b.y - o.y) else self.yColor
            self.drawSolidLine(o, b, scale, color)
            self.drawDot(b, scale, self.dotColor)
            mid = NSPoint((o.x + b.x) * 0.5, (o.y + b.y) * 0.5)
            self.drawTag(_format_distance(d, scale), mid, scale, color, self.whiteText)

    # ----- selection X/Y (a node selected) -------------------------------

    @objc.python_method
    def drawSelectionMeasure(self, layer, work, a, scale):
        cursor = self.mousePositionInGlyph()
        if cursor is None:
            return
        b = self.nearestTargetPoint(layer, work, cursor, scale, a)
        if b is None:
            return

        dx = b.x - a.x
        dy = b.y - a.y
        hasX = abs(dx) >= MIN_LEG
        hasY = abs(dy) >= MIN_LEG
        c1 = NSPoint(b.x, a.y)   # measured elbow: horizontal leg then vertical
        c2 = NSPoint(a.x, b.y)   # opposite corner, completes the rectangle

        # Rectangle completion (the other two sides), dashed and faint.
        if hasX and hasY:
            self.drawDashedLine(a, c2, scale, self.yColor.colorWithAlphaComponent_(0.45))
            self.drawDashedLine(c2, b, scale, self.xColor.colorWithAlphaComponent_(0.45))

        # Measured legs, solid so they read over outlines and handles.
        if hasX:
            self.drawSolidLine(a, c1, scale, self.xColor)
        if hasY:
            self.drawSolidLine(c1, b, scale, self.yColor)

        # Markers at the anchor, the elbow, and the hovered target.
        self.drawDot(a, scale, self.dotColor)
        self.drawDot(c1, scale, self.dotColor)
        self.drawDot(b, scale, self.dotColor)
        if hasX and hasY:
            self.drawDot(c2, scale, self.dotColor)

        if hasX:
            mid = NSPoint((a.x + c1.x) * 0.5, a.y)
            self.drawTag(_format_distance(abs(dx), scale), mid, scale, self.xColor, self.whiteText)
        if hasY:
            mid = NSPoint(c1.x, (c1.y + b.y) * 0.5)
            self.drawTag(_format_distance(abs(dy), scale), mid, scale, self.yColor, self.whiteText)

    # ----- entry ---------------------------------------------------------

    # ----- fade-in -------------------------------------------------------

    @objc.python_method
    def ensureFadeTimer(self):
        """Drive a few redraws over the fade window (the canvas won't animate
        itself). Short-lived; self-invalidates when the fade is done."""
        if NSTimer is None or self._fadeTimer is not None:
            return
        try:
            self._fadeTimer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.0 / 60.0, self, "fadeTick:", None, True)
        except Exception:
            self._fadeTimer = None

    def fadeTick_(self, timer):
        try:
            Glyphs.redraw()
            done = (not self.optionIsHeld()) or self._appearTime is None \
                or (time.time() - self._appearTime) > (FADE_SEC + 0.05)
            if done:
                timer.invalidate()
                if self._fadeTimer is timer:
                    self._fadeTimer = None
        except Exception:
            try:
                timer.invalidate()
            except Exception:
                pass
            self._fadeTimer = None

    @objc.python_method
    def fadeAlpha(self):
        """Alpha for this frame: ramps 0->1 over FADE_SEC from when the
        measurement first appeared; 1 once it's been showing."""
        if not FADE_SEC or FADE_SEC <= 0:
            return 1.0
        now = time.time()
        if not self._wasShowing:
            self._appearTime = now  # fresh appearance: restart the fade
        start = self._appearTime if self._appearTime is not None else now
        return min(1.0, max(0.0, (now - start) / FADE_SEC))

    # ----- entry ---------------------------------------------------------

    @objc.python_method
    def foreground(self, layer):
        if not self.optionIsHeld():
            self._wasShowing = False  # so the next Option-press fades in
            return
        if self.commandIsHeld():  # Option+Command is the zoom gesture
            self._wasShowing = False
            return

        scale = self.getScale()
        # No zoom limit: the measurement shows at any zoom level.

        alpha = self.fadeAlpha()
        self._didDraw = False

        ctx = NSGraphicsContext.currentContext()
        wrapped = False
        if alpha < 1.0 and CGContextSetAlpha is not None and ctx is not None:
            ctx.saveGraphicsState()
            try:
                CGContextSetAlpha(ctx.CGContext(), alpha)
                wrapped = True
            except Exception:
                ctx.restoreGraphicsState()

        try:
            work = self.workingLayer(layer)
            anchorPos = self.selectedAnchor(layer)
            if anchorPos is not None:
                self.drawSelectionMeasure(layer, work, anchorPos, scale)
            else:
                self.drawStemRuler(work, scale)
        finally:
            if wrapped:
                ctx.restoreGraphicsState()

        if self._didDraw and alpha < 1.0:
            self.ensureFadeTimer()
        self._wasShowing = self._didDraw

    @objc.python_method
    def __file__(self):
        """Please leave this method unchanged"""
        return __file__
