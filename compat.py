# -*- coding: utf-8 -*-
"""
PyQt5 / PyQt6 and QGIS 3.x / 4.x enum compatibility.

Two categories of breakage when migrating from QGIS 3.x (PyQt5) to QGIS 4.x (PyQt6):

1. PyQt5 → PyQt6: Qt enum members moved into sub-classes
       PyQt5:  Qt.AlignCenter
       PyQt6:  Qt.AlignmentFlag.AlignCenter

2. QGIS 3 → QGIS 4: QGIS-specific enum members moved into sub-classes or different classes
       QGIS 3:  QgsWkbTypes.PolygonGeometry
       QGIS 4:  Qgis.GeometryType.Polygon

Both are patched back with the _patch() helper so all plugin code works unchanged
on both versions.  Import this module ONCE, before any other plugin module is loaded.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QPainter
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox,
    QFrame, QHeaderView, QSizePolicy, QTableWidget, QToolButton,
)


def _patch(obj, name, provider):
    """Set obj.name = provider() only when the attribute is missing (PyQt6 style)."""
    if not hasattr(obj, name):
        try:
            setattr(obj, name, provider())
        except Exception:
            pass


# ── Qt — AlignmentFlag ────────────────────────────────────────────────────────
_patch(Qt, 'AlignLeft',    lambda: Qt.AlignmentFlag.AlignLeft)
_patch(Qt, 'AlignRight',   lambda: Qt.AlignmentFlag.AlignRight)
_patch(Qt, 'AlignTop',     lambda: Qt.AlignmentFlag.AlignTop)
_patch(Qt, 'AlignBottom',  lambda: Qt.AlignmentFlag.AlignBottom)
_patch(Qt, 'AlignHCenter', lambda: Qt.AlignmentFlag.AlignHCenter)
_patch(Qt, 'AlignVCenter', lambda: Qt.AlignmentFlag.AlignVCenter)
_patch(Qt, 'AlignCenter',  lambda: Qt.AlignmentFlag.AlignCenter)

# ── Qt — WindowType ───────────────────────────────────────────────────────────
_patch(Qt, 'Window',                   lambda: Qt.WindowType.Window)
_patch(Qt, 'Dialog',                   lambda: Qt.WindowType.Dialog)
_patch(Qt, 'WindowTitleHint',          lambda: Qt.WindowType.WindowTitleHint)
_patch(Qt, 'WindowMinimizeButtonHint', lambda: Qt.WindowType.WindowMinimizeButtonHint)
_patch(Qt, 'WindowMaximizeButtonHint', lambda: Qt.WindowType.WindowMaximizeButtonHint)
_patch(Qt, 'WindowCloseButtonHint',    lambda: Qt.WindowType.WindowCloseButtonHint)
_patch(Qt, 'WindowStaysOnTopHint',     lambda: Qt.WindowType.WindowStaysOnTopHint)
_patch(Qt, 'FramelessWindowHint',      lambda: Qt.WindowType.FramelessWindowHint)

# ── Qt — CursorShape ─────────────────────────────────────────────────────────
_patch(Qt, 'ArrowCursor',       lambda: Qt.CursorShape.ArrowCursor)
_patch(Qt, 'CrossCursor',       lambda: Qt.CursorShape.CrossCursor)
_patch(Qt, 'WaitCursor',        lambda: Qt.CursorShape.WaitCursor)
_patch(Qt, 'PointingHandCursor', lambda: Qt.CursorShape.PointingHandCursor)
_patch(Qt, 'BlankCursor',       lambda: Qt.CursorShape.BlankCursor)

# ── Qt — MouseButton ─────────────────────────────────────────────────────────
_patch(Qt, 'LeftButton',   lambda: Qt.MouseButton.LeftButton)
_patch(Qt, 'RightButton',  lambda: Qt.MouseButton.RightButton)
_patch(Qt, 'MiddleButton', lambda: Qt.MouseButton.MiddleButton)
_patch(Qt, 'MidButton',    lambda: Qt.MouseButton.MiddleButton)

# ── Qt — Key ─────────────────────────────────────────────────────────────────
_patch(Qt, 'Key_Escape',    lambda: Qt.Key.Key_Escape)
_patch(Qt, 'Key_Return',    lambda: Qt.Key.Key_Return)
_patch(Qt, 'Key_Enter',     lambda: Qt.Key.Key_Enter)
_patch(Qt, 'Key_Delete',    lambda: Qt.Key.Key_Delete)
_patch(Qt, 'Key_Backspace', lambda: Qt.Key.Key_Backspace)
_patch(Qt, 'Key_Tab',       lambda: Qt.Key.Key_Tab)
_patch(Qt, 'Key_Space',     lambda: Qt.Key.Key_Space)
_patch(Qt, 'Key_Control',   lambda: Qt.Key.Key_Control)
_patch(Qt, 'Key_Shift',     lambda: Qt.Key.Key_Shift)
_patch(Qt, 'Key_Alt',       lambda: Qt.Key.Key_Alt)
_patch(Qt, 'Key_Meta',      lambda: Qt.Key.Key_Meta)
_patch(Qt, 'Key_AltGr',     lambda: Qt.Key.Key_AltGr)
_patch(Qt, 'Key_Super_L',   lambda: Qt.Key.Key_Super_L)
_patch(Qt, 'Key_Super_R',   lambda: Qt.Key.Key_Super_R)
_patch(Qt, 'Key_unknown',   lambda: Qt.Key.Key_unknown)

# ── Qt — ItemDataRole ─────────────────────────────────────────────────────────
_patch(Qt, 'UserRole',       lambda: Qt.ItemDataRole.UserRole)
_patch(Qt, 'DisplayRole',    lambda: Qt.ItemDataRole.DisplayRole)
_patch(Qt, 'DecorationRole', lambda: Qt.ItemDataRole.DecorationRole)
_patch(Qt, 'CheckStateRole', lambda: Qt.ItemDataRole.CheckStateRole)
_patch(Qt, 'ToolTipRole',    lambda: Qt.ItemDataRole.ToolTipRole)

# ── Qt — AspectRatioMode / TransformationMode ─────────────────────────────────
_patch(Qt, 'KeepAspectRatio',      lambda: Qt.AspectRatioMode.KeepAspectRatio)
_patch(Qt, 'IgnoreAspectRatio',    lambda: Qt.AspectRatioMode.IgnoreAspectRatio)
_patch(Qt, 'SmoothTransformation', lambda: Qt.TransformationMode.SmoothTransformation)
_patch(Qt, 'FastTransformation',   lambda: Qt.TransformationMode.FastTransformation)

# ── Qt — ShortcutContext ──────────────────────────────────────────────────────
_patch(Qt, 'ApplicationShortcut', lambda: Qt.ShortcutContext.ApplicationShortcut)
_patch(Qt, 'WindowShortcut',      lambda: Qt.ShortcutContext.WindowShortcut)
_patch(Qt, 'WidgetShortcut',      lambda: Qt.ShortcutContext.WidgetShortcut)

# ── Qt — WindowModality ───────────────────────────────────────────────────────
_patch(Qt, 'NonModal',          lambda: Qt.WindowModality.NonModal)
_patch(Qt, 'WindowModal',       lambda: Qt.WindowModality.WindowModal)
_patch(Qt, 'ApplicationModal',  lambda: Qt.WindowModality.ApplicationModal)

# ── Qt — ToolButtonStyle (was flat on Qt in PyQt5) ───────────────────────────
_patch(Qt, 'ToolButtonIconOnly',       lambda: Qt.ToolButtonStyle.ToolButtonIconOnly)
_patch(Qt, 'ToolButtonTextOnly',       lambda: Qt.ToolButtonStyle.ToolButtonTextOnly)
_patch(Qt, 'ToolButtonTextBesideIcon', lambda: Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
_patch(Qt, 'ToolButtonTextUnderIcon',  lambda: Qt.ToolButtonStyle.ToolButtonTextUnderIcon)

# ── Qt — CheckState ───────────────────────────────────────────────────────────
_patch(Qt, 'Checked',          lambda: Qt.CheckState.Checked)
_patch(Qt, 'Unchecked',        lambda: Qt.CheckState.Unchecked)
_patch(Qt, 'PartiallyChecked', lambda: Qt.CheckState.PartiallyChecked)

# ── Qt — TextFormat ──────────────────────────────────────────────────────────
_patch(Qt, 'PlainText',    lambda: Qt.TextFormat.PlainText)
_patch(Qt, 'RichText',     lambda: Qt.TextFormat.RichText)
_patch(Qt, 'AutoText',     lambda: Qt.TextFormat.AutoText)
_patch(Qt, 'MarkdownText', lambda: Qt.TextFormat.MarkdownText)

# ── Qt — TextElideMode ───────────────────────────────────────────────────────
_patch(Qt, 'ElideLeft',   lambda: Qt.TextElideMode.ElideLeft)
_patch(Qt, 'ElideRight',  lambda: Qt.TextElideMode.ElideRight)
_patch(Qt, 'ElideMiddle', lambda: Qt.TextElideMode.ElideMiddle)
_patch(Qt, 'ElideNone',   lambda: Qt.TextElideMode.ElideNone)

# ── Qt — CaseSensitivity ─────────────────────────────────────────────────────
_patch(Qt, 'CaseSensitive',   lambda: Qt.CaseSensitivity.CaseSensitive)
_patch(Qt, 'CaseInsensitive', lambda: Qt.CaseSensitivity.CaseInsensitive)

# ── Qt — ScrollBarPolicy ──────────────────────────────────────────────────────
_patch(Qt, 'ScrollBarAsNeeded',  lambda: Qt.ScrollBarPolicy.ScrollBarAsNeeded)
_patch(Qt, 'ScrollBarAlwaysOff', lambda: Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
_patch(Qt, 'ScrollBarAlwaysOn',  lambda: Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

# ── Qt — misc ─────────────────────────────────────────────────────────────────
_patch(Qt, 'Horizontal', lambda: Qt.Orientation.Horizontal)
_patch(Qt, 'Vertical',   lambda: Qt.Orientation.Vertical)
_patch(Qt, 'WordWrap',   lambda: Qt.TextFlag.TextWordWrap)

# ── QPainter — RenderHint ─────────────────────────────────────────────────────
_patch(QPainter, 'Antialiasing',       lambda: QPainter.RenderHint.Antialiasing)
_patch(QPainter, 'SmoothPixmapTransform', lambda: QPainter.RenderHint.SmoothPixmapTransform)
_patch(QPainter, 'TextAntialiasing',   lambda: QPainter.RenderHint.TextAntialiasing)

# ── QFrame ───────────────────────────────────────────────────────────────────
_patch(QFrame, 'HLine',   lambda: QFrame.Shape.HLine)
_patch(QFrame, 'VLine',   lambda: QFrame.Shape.VLine)
_patch(QFrame, 'NoFrame', lambda: QFrame.Shape.NoFrame)
_patch(QFrame, 'Box',     lambda: QFrame.Shape.Box)
_patch(QFrame, 'Panel',   lambda: QFrame.Shape.Panel)
_patch(QFrame, 'Sunken',  lambda: QFrame.Shadow.Sunken)
_patch(QFrame, 'Raised',  lambda: QFrame.Shadow.Raised)
_patch(QFrame, 'Plain',   lambda: QFrame.Shadow.Plain)

# ── QToolButton ───────────────────────────────────────────────────────────────
_patch(QToolButton, 'InstantPopup',   lambda: QToolButton.ToolButtonPopupMode.InstantPopup)
_patch(QToolButton, 'DelayedPopup',   lambda: QToolButton.ToolButtonPopupMode.DelayedPopup)
_patch(QToolButton, 'MenuButtonPopup', lambda: QToolButton.ToolButtonPopupMode.MenuButtonPopup)

# ── QAbstractItemView ─────────────────────────────────────────────────────────
_patch(QAbstractItemView, 'SingleSelection',   lambda: QAbstractItemView.SelectionMode.SingleSelection)
_patch(QAbstractItemView, 'ExtendedSelection', lambda: QAbstractItemView.SelectionMode.ExtendedSelection)
_patch(QAbstractItemView, 'MultiSelection',    lambda: QAbstractItemView.SelectionMode.MultiSelection)
_patch(QAbstractItemView, 'NoSelection',       lambda: QAbstractItemView.SelectionMode.NoSelection)
_patch(QAbstractItemView, 'ContiguousSelection', lambda: QAbstractItemView.SelectionMode.ContiguousSelection)
_patch(QAbstractItemView, 'SelectItems',   lambda: QAbstractItemView.SelectionBehavior.SelectItems)
_patch(QAbstractItemView, 'SelectRows',    lambda: QAbstractItemView.SelectionBehavior.SelectRows)
_patch(QAbstractItemView, 'SelectColumns', lambda: QAbstractItemView.SelectionBehavior.SelectColumns)
_patch(QAbstractItemView, 'NoEditTriggers',  lambda: QAbstractItemView.EditTrigger.NoEditTriggers)
_patch(QAbstractItemView, 'AllEditTriggers', lambda: QAbstractItemView.EditTrigger.AllEditTriggers)
_patch(QAbstractItemView, 'CurrentChanged',  lambda: QAbstractItemView.EditTrigger.CurrentChanged)
_patch(QAbstractItemView, 'DoubleClicked',   lambda: QAbstractItemView.EditTrigger.DoubleClicked)
_patch(QAbstractItemView, 'SelectedClicked', lambda: QAbstractItemView.EditTrigger.SelectedClicked)
_patch(QAbstractItemView, 'EditKeyPressed',  lambda: QAbstractItemView.EditTrigger.EditKeyPressed)
_patch(QAbstractItemView, 'AnyKeyPressed',   lambda: QAbstractItemView.EditTrigger.AnyKeyPressed)

# ── QTableWidget — EditTrigger (inherits QAbstractItemView but C++ MRO may not expose patched attrs) ─
_patch(QTableWidget, 'NoEditTriggers',  lambda: QAbstractItemView.EditTrigger.NoEditTriggers)
_patch(QTableWidget, 'AllEditTriggers', lambda: QAbstractItemView.EditTrigger.AllEditTriggers)

# ── QHeaderView ───────────────────────────────────────────────────────────────
_patch(QHeaderView, 'ResizeToContents', lambda: QHeaderView.ResizeMode.ResizeToContents)
_patch(QHeaderView, 'Stretch',          lambda: QHeaderView.ResizeMode.Stretch)
_patch(QHeaderView, 'Fixed',            lambda: QHeaderView.ResizeMode.Fixed)
_patch(QHeaderView, 'Interactive',      lambda: QHeaderView.ResizeMode.Interactive)
_patch(QHeaderView, 'Custom',           lambda: QHeaderView.ResizeMode.Custom)

# ── QSizePolicy ───────────────────────────────────────────────────────────────
_patch(QSizePolicy, 'Fixed',            lambda: QSizePolicy.Policy.Fixed)
_patch(QSizePolicy, 'Minimum',          lambda: QSizePolicy.Policy.Minimum)
_patch(QSizePolicy, 'Maximum',          lambda: QSizePolicy.Policy.Maximum)
_patch(QSizePolicy, 'Preferred',        lambda: QSizePolicy.Policy.Preferred)
_patch(QSizePolicy, 'Expanding',        lambda: QSizePolicy.Policy.Expanding)
_patch(QSizePolicy, 'MinimumExpanding', lambda: QSizePolicy.Policy.MinimumExpanding)
_patch(QSizePolicy, 'Ignored',          lambda: QSizePolicy.Policy.Ignored)

# ── QDialogButtonBox ──────────────────────────────────────────────────────────
_patch(QDialogButtonBox, 'Ok',       lambda: QDialogButtonBox.StandardButton.Ok)
_patch(QDialogButtonBox, 'Cancel',   lambda: QDialogButtonBox.StandardButton.Cancel)
_patch(QDialogButtonBox, 'Apply',    lambda: QDialogButtonBox.StandardButton.Apply)
_patch(QDialogButtonBox, 'Close',    lambda: QDialogButtonBox.StandardButton.Close)
_patch(QDialogButtonBox, 'Save',     lambda: QDialogButtonBox.StandardButton.Save)
_patch(QDialogButtonBox, 'Discard',  lambda: QDialogButtonBox.StandardButton.Discard)
_patch(QDialogButtonBox, 'Reset',    lambda: QDialogButtonBox.StandardButton.Reset)
_patch(QDialogButtonBox, 'Yes',      lambda: QDialogButtonBox.StandardButton.Yes)
_patch(QDialogButtonBox, 'No',       lambda: QDialogButtonBox.StandardButton.No)


# =============================================================================
# QGIS 3 → QGIS 4 enum migration patches
# =============================================================================
# QGIS 4 moved many enum members out of flat class attributes into typed
# sub-classes (parallel to the PyQt5 → PyQt6 migration above).
# The _patch() helper is a no-op when the attribute already exists (QGIS 3),
# so these blocks are safe to import on any QGIS version.

try:
    from qgis.core import Qgis, QgsWkbTypes, QgsUnitTypes, QgsPalLayerSettings
    from qgis.gui import QgsRubberBand as _QgsRubberBand

    # ── QgsWkbTypes — GeometryType (QGIS 3 flat → Qgis.GeometryType in QGIS 4) ──
    _patch(QgsWkbTypes, 'PointGeometry',   lambda: Qgis.GeometryType.Point)
    _patch(QgsWkbTypes, 'LineGeometry',    lambda: Qgis.GeometryType.Line)
    _patch(QgsWkbTypes, 'PolygonGeometry', lambda: Qgis.GeometryType.Polygon)
    _patch(QgsWkbTypes, 'NullGeometry',    lambda: Qgis.GeometryType.Null)
    _patch(QgsWkbTypes, 'UnknownGeometry', lambda: Qgis.GeometryType.Unknown)

    # ── QgsWkbTypes — Type (WKB type constants) ───────────────────────────────
    _patch(QgsWkbTypes, 'Point',               lambda: QgsWkbTypes.Type.Point)
    _patch(QgsWkbTypes, 'LineString',          lambda: QgsWkbTypes.Type.LineString)
    _patch(QgsWkbTypes, 'Polygon',             lambda: QgsWkbTypes.Type.Polygon)
    _patch(QgsWkbTypes, 'MultiPoint',          lambda: QgsWkbTypes.Type.MultiPoint)
    _patch(QgsWkbTypes, 'MultiLineString',     lambda: QgsWkbTypes.Type.MultiLineString)
    _patch(QgsWkbTypes, 'MultiPolygon',        lambda: QgsWkbTypes.Type.MultiPolygon)
    _patch(QgsWkbTypes, 'GeometryCollection',  lambda: QgsWkbTypes.Type.GeometryCollection)
    _patch(QgsWkbTypes, 'NoGeometry',          lambda: QgsWkbTypes.Type.NoGeometry)
    _patch(QgsWkbTypes, 'Unknown',             lambda: QgsWkbTypes.Type.Unknown)
    _patch(QgsWkbTypes, 'PointZ',              lambda: QgsWkbTypes.Type.PointZ)
    _patch(QgsWkbTypes, 'LineStringZ',         lambda: QgsWkbTypes.Type.LineStringZ)
    _patch(QgsWkbTypes, 'PolygonZ',            lambda: QgsWkbTypes.Type.PolygonZ)
    _patch(QgsWkbTypes, 'MultiPointZ',         lambda: QgsWkbTypes.Type.MultiPointZ)
    _patch(QgsWkbTypes, 'MultiLineStringZ',    lambda: QgsWkbTypes.Type.MultiLineStringZ)
    _patch(QgsWkbTypes, 'MultiPolygonZ',       lambda: QgsWkbTypes.Type.MultiPolygonZ)

    # ── QgsUnitTypes — DistanceUnit (QGIS 3 flat → Qgis.DistanceUnit in QGIS 4) ─
    _patch(QgsUnitTypes, 'DistanceMeters',        lambda: Qgis.DistanceUnit.Meters)
    _patch(QgsUnitTypes, 'DistanceFeet',          lambda: Qgis.DistanceUnit.Feet)
    _patch(QgsUnitTypes, 'DistanceKilometers',    lambda: Qgis.DistanceUnit.Kilometers)
    _patch(QgsUnitTypes, 'DistanceMiles',         lambda: Qgis.DistanceUnit.Miles)
    _patch(QgsUnitTypes, 'DistanceYards',         lambda: Qgis.DistanceUnit.Yards)
    _patch(QgsUnitTypes, 'DistanceDegrees',       lambda: Qgis.DistanceUnit.Degrees)
    _patch(QgsUnitTypes, 'DistanceNauticalMiles', lambda: Qgis.DistanceUnit.NauticalMiles)
    _patch(QgsUnitTypes, 'DistanceCentimeters',   lambda: Qgis.DistanceUnit.Centimeters)
    _patch(QgsUnitTypes, 'DistanceMillimeters',   lambda: Qgis.DistanceUnit.Millimeters)
    _patch(QgsUnitTypes, 'DistanceUnknownUnit',   lambda: Qgis.DistanceUnit.Unknown)

    # ── QgsRubberBand — IconType ──────────────────────────────────────────────
    _patch(_QgsRubberBand, 'ICON_NONE',    lambda: _QgsRubberBand.IconType.ICON_NONE)
    _patch(_QgsRubberBand, 'ICON_CROSS',   lambda: _QgsRubberBand.IconType.ICON_CROSS)
    _patch(_QgsRubberBand, 'ICON_CIRCLE',  lambda: _QgsRubberBand.IconType.ICON_CIRCLE)
    _patch(_QgsRubberBand, 'ICON_X',       lambda: _QgsRubberBand.IconType.ICON_X)
    _patch(_QgsRubberBand, 'ICON_BOX',     lambda: _QgsRubberBand.IconType.ICON_BOX)
    _patch(_QgsRubberBand, 'ICON_DIAMOND', lambda: _QgsRubberBand.IconType.ICON_DIAMOND)
    _patch(_QgsRubberBand, 'ICON_FULL_DIAMOND', lambda: _QgsRubberBand.IconType.ICON_FULL_DIAMOND)
    _patch(_QgsRubberBand, 'ICON_SVG',     lambda: _QgsRubberBand.IconType.ICON_SVG)

    # ── QgsPalLayerSettings — Placement ──────────────────────────────────────
    _patch(QgsPalLayerSettings, 'AroundPoint',   lambda: QgsPalLayerSettings.Placement.AroundPoint)
    _patch(QgsPalLayerSettings, 'OverPoint',     lambda: QgsPalLayerSettings.Placement.OverPoint)
    _patch(QgsPalLayerSettings, 'Line',          lambda: QgsPalLayerSettings.Placement.Line)
    _patch(QgsPalLayerSettings, 'Curved',        lambda: QgsPalLayerSettings.Placement.Curved)
    _patch(QgsPalLayerSettings, 'Horizontal',    lambda: QgsPalLayerSettings.Placement.Horizontal)
    _patch(QgsPalLayerSettings, 'Free',          lambda: QgsPalLayerSettings.Placement.Free)
    _patch(QgsPalLayerSettings, 'OrderedPositionsAroundPoint',
                                                  lambda: QgsPalLayerSettings.Placement.OrderedPositionsAroundPoint)
    _patch(QgsPalLayerSettings, 'PerimeterCurved', lambda: QgsPalLayerSettings.Placement.PerimeterCurved)
    _patch(QgsPalLayerSettings, 'OutsidePolygons', lambda: QgsPalLayerSettings.Placement.OutsidePolygons)

    # ── Qgis — MessageLevel (QGIS 3 flat ints → Qgis.MessageLevel in QGIS 4) ─────
    # Also backfill Qgis.MessageLevel for very old QGIS 3.x that lacks it.
    if not hasattr(Qgis, 'MessageLevel'):
        class _ML:
            Info     = getattr(Qgis, 'Info',     0)
            Warning  = getattr(Qgis, 'Warning',  1)
            Critical = getattr(Qgis, 'Critical', 2)
            Success  = getattr(Qgis, 'Success',  3)
        Qgis.MessageLevel = _ML

    # Flat aliases for code that still uses Qgis.Info etc.
    _patch(Qgis, 'Info',     lambda: Qgis.MessageLevel.Info)
    _patch(Qgis, 'Warning',  lambda: Qgis.MessageLevel.Warning)
    _patch(Qgis, 'Critical', lambda: Qgis.MessageLevel.Critical)
    _patch(Qgis, 'Success',  lambda: Qgis.MessageLevel.Success)

except Exception:
    pass  # QGIS modules not available (unit-test environment or import error)


# ── QDialog — exec_ alias and DialogCode ─────────────────────────────────────
if not hasattr(QDialog, 'exec_'):
    QDialog.exec_ = lambda self: self.exec()
_patch(QDialog, 'Accepted', lambda: QDialog.DialogCode.Accepted)
_patch(QDialog, 'Rejected', lambda: QDialog.DialogCode.Rejected)
