# coding=utf-8
"""Dialog test.

.. note:: This program is free software; you can redistribute it and/or modify
     it under the terms of the GNU General Public License as published by
     the Free Software Foundation; either version 2 of the License, or
     (at your option) any later version.

"""

__author__ = 'lucianoufscagve@gmail.com'
__date__ = '2026-03-11'
__copyright__ = 'Copyright 2026, Rithon'

import unittest

_QGIS_AVAILABLE = False
try:
    from qgis.PyQt.QtWidgets import QDialogButtonBox, QDialog
    try:
        from .utilities import get_qgis_app
    except (ImportError, SystemError):
        from utilities import get_qgis_app
    import importlib.util as _ilu, os as _os
    _spec = _ilu.spec_from_file_location(
        'RTH_PROJECT_dialog',
        _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), 'RTH PROJECT_dialog.py')
    )
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    rthprojectDialog = _mod.rthprojectDialog
    QGIS_APP = get_qgis_app()
    _QGIS_AVAILABLE = QGIS_APP is not None and QGIS_APP[0] is not None
except Exception:  # nosec B110
    pass


@unittest.skipUnless(_QGIS_AVAILABLE, 'QGIS runtime not available')
class rthprojectDialogTest(unittest.TestCase):
    """Test dialog works."""

    def setUp(self):
        """Runs before each test."""
        self.dialog = rthprojectDialog(None)

    def tearDown(self):
        """Runs after each test."""
        self.dialog = None

    def test_dialog_ok(self):
        """Test we can click OK."""

        button = self.dialog.button_box.button(QDialogButtonBox.Ok)
        button.click()
        result = self.dialog.result()
        self.assertEqual(result, QDialog.Accepted)

    def test_dialog_cancel(self):
        """Test we can click cancel."""
        button = self.dialog.button_box.button(QDialogButtonBox.Cancel)
        button.click()
        result = self.dialog.result()
        self.assertEqual(result, QDialog.Rejected)

if __name__ == "__main__":
    suite = unittest.makeSuite(rthprojectDialogTest)
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)

