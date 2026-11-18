# Incoming Bluetooth startup

The pinned stock daemon initializes incoming AVDTP session grace to 30 seconds. This can delay local discovery when the receiver waits for the Q2. tools/bluetoothd.py changes that initializer to one second after checking the full stock hash, size, instruction and surrounding bytes. Outgoing sessions bypass the initializer; configured and Close/Abort reset paths are unchanged. Incoming preconfiguration idle/failed-setup cleanup also uses this grace, so the change is not Tesla-specific.

Earlier combined firmware trials showed prompt sound on Tesla and AirPods. Recorded Tesla configuration-to-Discover intervals fell from 30.062689 seconds to 1.130859 and 0.881116 seconds. This is not exhaustive receiver compatibility testing and not hardware validation of this newly split branch.

Run pytest test/unit/test_bluetoothd.py test/unit/test_release.py, test/btincoming.py BUILD, and the normal build/archive checks. No metadata helper or diagnostic logger is included.
