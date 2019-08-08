#!/usr/bin/python3
"""
Ubuntu charm functional test using Zaza. Take note that the Ubuntu
charm does not have any relations or config options to exercise.
"""

import unittest
import zaza.model as model

class BasicDeployment(unittest.TestCase):
    def test_ubuntu_series(self):
        pass
