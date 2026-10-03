import unittest

from engine import linux_tls


class LinuxTlsTests(unittest.TestCase):
    def configure(self, files, environ=None, platform="linux", fallback=""):
        environ = {} if environ is None else environ
        chosen = linux_tls.configure(environ, platform, exists=lambda path: path in files,
                                     fallback=lambda: fallback)
        return chosen, environ

    def test_fedora_bundle_is_used_when_ubuntu_path_is_missing(self):
        fedora = "/etc/pki/tls/certs/ca-bundle.crt"
        chosen, environ = self.configure({fedora})
        self.assertEqual(chosen, fedora)
        self.assertEqual(environ["SSL_CERT_FILE"], fedora)

    def test_debian_and_arch_bundle_comes_first(self):
        files = {"/etc/ssl/certs/ca-certificates.crt", "/etc/ssl/cert.pem"}
        chosen, _ = self.configure(files)
        self.assertEqual(chosen, "/etc/ssl/certs/ca-certificates.crt")

    def test_bundled_certifi_when_system_has_no_bundle(self):
        chosen, environ = self.configure({"/app/certifi/cacert.pem"}, fallback="/app/certifi/cacert.pem")
        self.assertEqual(environ["SSL_CERT_FILE"], "/app/certifi/cacert.pem")
        self.assertEqual(chosen, "/app/certifi/cacert.pem")

    def test_nothing_found_leaves_environment_alone(self):
        chosen, environ = self.configure(set())
        self.assertEqual((chosen, environ), ("", {}))

    def test_user_choice_is_respected(self):
        for key in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
            chosen, environ = self.configure({"/etc/pki/tls/certs/ca-bundle.crt"}, {key: "/mine"})
            self.assertEqual((chosen, environ), ("", {key: "/mine"}))

    def test_windows_is_untouched(self):
        chosen, environ = self.configure({"/etc/ssl/certs/ca-certificates.crt"}, platform="win32")
        self.assertEqual((chosen, environ), ("", {}))


if __name__ == "__main__":
    unittest.main()
