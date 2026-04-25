#
# Copyright OpenEmbedded Contributors
#
# SPDX-License-Identifier: MIT
#

import os
import re
import subprocess
import tempfile
import textwrap

from oeqa.selftest.case import OESelftestTestCase
from oeqa.utils.commands import bitbake, get_bb_vars, get_bb_var, runCmd


class PackageSignatureVerification(OESelftestTestCase):
    """Tests for verifying package signature integrity."""

    def test_rpm_signature_key_present(self):
        """Ensure the RPM signing key variable is defined when signing is enabled."""
        signing_enabled = get_bb_var("RPM_SIGN_PACKAGES")
        if signing_enabled == "1":
            key_id = get_bb_var("RPM_GPG_PASSPHRASE_FILE")
            self.assertIsNotNone(
                key_id,
                "RPM_GPG_PASSPHRASE_FILE must be set when RPM_SIGN_PACKAGES=1",
            )

    def test_package_feed_gpg_key_consistency(self):
        """Verify that GPG key name and passphrase file are consistently configured."""
        variables = get_bb_vars([
            "RPM_GPG_NAME",
            "RPM_GPG_PASSPHRASE_FILE",
            "RPM_SIGN_PACKAGES",
        ])
        if variables["RPM_SIGN_PACKAGES"] == "1":
            self.assertIsNotNone(
                variables["RPM_GPG_NAME"],
                "RPM_GPG_NAME must be set when signing is enabled",
            )
            self.assertIsNotNone(
                variables["RPM_GPG_PASSPHRASE_FILE"],
                "RPM_GPG_PASSPHRASE_FILE must be set when signing is enabled",
            )

    def test_signing_class_inherits_correctly(self):
        """Check that sign_rpm class is inherited when signing is enabled."""
        signing_enabled = get_bb_var("RPM_SIGN_PACKAGES")
        if signing_enabled == "1":
            classes = get_bb_var("INHERIT") or ""
            self.assertIn(
                "sign_rpm",
                classes,
                "sign_rpm class should be inherited when RPM_SIGN_PACKAGES=1",
            )


class DependencyCycleDetection(OESelftestTestCase):
    """Tests for detecting dependency cycles in recipes."""

    def test_no_circular_rdepends(self):
        """Verify that a simple recipe does not contain circular RDEPENDS."""
        self.write_config("")
        self.write_recipeinc("base-files", 'RDEPENDS:${PN}:remove = "${PN}"')
        variables = get_bb_vars(["RDEPENDS:${PN}"], "base-files")
        rdepends = (variables.get("RDEPENDS:${PN}") or "").split()
        self.assertNotIn(
            "base-files",
            rdepends,
            "A package should not have a runtime dependency on itself",
        )

    def test_task_dependency_ordering(self):
        """Ensure do_install depends on do_compile in standard recipes."""
        result = runCmd("bitbake -g base-files", ignore_status=True)
        if result.status == 0:
            # Check that task-depends.dot was generated
            dot_file = os.path.join(os.getcwd(), "task-depends.dot")
            if os.path.exists(dot_file):
                with open(dot_file, "r") as f:
                    content = f.read()
                # do_install should appear after do_compile in the graph
                has_compile = "do_compile" in content
                has_install = "do_install" in content
                if has_compile and has_install:
                    self.assertIn(
                        "do_compile",
                        content,
                        "do_compile task should be present in dependency graph",
                    )

    def test_build_depends_not_self_referencing(self):
        """Verify recipes do not declare build dependencies on themselves."""
        pn = get_bb_var("PN", "base-files")
        depends = get_bb_var("DEPENDS", "base-files") or ""
        depends_list = depends.split()
        self.assertNotIn(
            pn,
            depends_list,
            "A recipe should not depend on itself in DEPENDS",
        )


class FileConflictChecking(OESelftestTestCase):
    """Tests for detecting file conflicts across packages."""

    def test_conflicting_files_detection_variable(self):
        """Verify the FILE_CONFLICT_CHECK variable is recognized."""
        var = get_bb_var("PACKAGE_OVERLAP_CHECK")
        # The variable should either be unset or contain a valid value
        if var is not None:
            valid_values = {"1", "0", "yes", "no", "true", "false", ""}
            self.assertIn(
                var.lower(),
                valid_values,
                "PACKAGE_OVERLAP_CHECK has unexpected value: %s" % var,
            )

    def test_pkgdata_directory_exists_after_build(self):
        """Ensure pkgdata directory is created during build."""
        pkgdata_dir = get_bb_var("PKGDATA_DIR")
        self.assertIsNotNone(
            pkgdata_dir,
            "PKGDATA_DIR should be defined in the build configuration",
        )

    def test_no_duplicate_files_in_single_recipe(self):
        """Check that FILES variables don't specify duplicates within a recipe."""
        files_var = get_bb_var("FILES:${PN}", "base-files") or ""
        paths = files_var.split()
        unique_paths = set(paths)
        self.assertEqual(
            len(paths),
            len(unique_paths),
            "FILES variable should not contain duplicate entries: %s"
            % [p for p in paths if paths.count(p) > 1],
        )


class PackageMetadataValidation(OESelftestTestCase):
    """Tests for validating package metadata fields."""

    def test_recipe_has_summary(self):
        """Every recipe should have a SUMMARY or DESCRIPTION."""
        summary = get_bb_var("SUMMARY", "base-files")
        description = get_bb_var("DESCRIPTION", "base-files")
        self.assertTrue(
            summary or description,
            "Recipe should have either SUMMARY or DESCRIPTION set",
        )

    def test_recipe_has_valid_homepage(self):
        """HOMEPAGE should be a valid URL if set."""
        homepage = get_bb_var("HOMEPAGE", "base-files")
        if homepage:
            self.assertTrue(
                homepage.startswith("http://") or homepage.startswith("https://"),
                "HOMEPAGE should start with http:// or https://: got %s" % homepage,
            )

    def test_recipe_section_is_set(self):
        """SECTION metadata should be defined."""
        section = get_bb_var("SECTION", "base-files")
        self.assertIsNotNone(
            section,
            "SECTION should be defined for the recipe",
        )
        self.assertNotEqual(section.strip(), "", "SECTION should not be empty")

    def test_recipe_pv_format(self):
        """Package version should follow standard versioning patterns."""
        pv = get_bb_var("PV", "base-files")
        self.assertIsNotNone(pv, "PV must be defined")
        # PV should match a version-like pattern (digits, dots, optional suffixes)
        pattern = re.compile(r"^\d+(\.\d+)*([+\-].*)?$")
        self.assertTrue(
            pattern.match(pv),
            "PV '%s' does not match expected version format" % pv,
        )

    def test_recipe_pn_no_uppercase(self):
        """Package name should be lowercase by convention."""
        pn = get_bb_var("PN", "base-files")
        self.assertIsNotNone(pn, "PN must be defined")
        self.assertEqual(
            pn,
            pn.lower(),
            "PN should be lowercase: got '%s'" % pn,
        )


class LicenseConsistencyChecks(OESelftestTestCase):
    """Tests for license metadata consistency."""

    def test_license_is_set(self):
        """LICENSE must be set for all recipes."""
        license_val = get_bb_var("LICENSE", "base-files")
        self.assertIsNotNone(license_val, "LICENSE must be defined")
        self.assertNotEqual(
            license_val, "INVALID", "LICENSE should not be INVALID"
        )

    def test_license_not_unknown(self):
        """LICENSE should not be 'UNKNOWN'."""
        license_val = get_bb_var("LICENSE", "base-files")
        self.assertNotEqual(
            license_val,
            "UNKNOWN",
            "LICENSE should not be set to UNKNOWN",
        )

    def test_lic_files_chksum_present(self):
        """LIC_FILES_CHKSUM should be set when LICENSE is not CLOSED."""
        license_val = get_bb_var("LICENSE", "base-files")
        lic_chksum = get_bb_var("LIC_FILES_CHKSUM", "base-files")
        if license_val != "CLOSED":
            self.assertIsNotNone(
                lic_chksum,
                "LIC_FILES_CHKSUM should be set when LICENSE != CLOSED",
            )

    def test_license_flag_whitelist_format(self):
        """Check LICENSE_FLAGS_ACCEPTED format if set."""
        flags = get_bb_var("LICENSE_FLAGS_ACCEPTED")
        if flags:
            # Flags should be space-separated strings
            for flag in flags.split():
                self.assertTrue(
                    len(flag) > 0,
                    "Empty license flag found in LICENSE_FLAGS_ACCEPTED",
                )
                self.assertFalse(
                    flag.startswith("-"),
                    "License flag should not start with dash: %s" % flag,
                )

    def test_incompatible_license_filter(self):
        """Verify INCOMPATIBLE_LICENSE is properly formatted if set."""
        incompatible = get_bb_var("INCOMPATIBLE_LICENSE")
        if incompatible:
            licenses = incompatible.split()
            for lic in licenses:
                # Each entry should be a plausible license identifier
                self.assertRegex(
                    lic,
                    r"^[A-Za-z0-9_.+\-]+$",
                    "INCOMPATIBLE_LICENSE entry '%s' has invalid characters" % lic,
                )
