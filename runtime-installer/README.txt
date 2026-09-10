SceneLight runtime slot
=======================

The normal source release does not redistribute Python. The Windows offline
release builder places an Authenticode-signed 64-bit Python installer in this
directory. SceneLight verifies that the signer is the Python Software
Foundation before offering a per-user installation.

The SceneLight runtime is installed under LocalAppData\SceneLight. It is not added
to PATH, does not claim file associations, and does not require administrator
access.
