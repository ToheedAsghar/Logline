import os
import signal
import subprocess
import time
from pathlib import Path
import sys

def test_graceful_shutdown():
    # Make sure we're in the right directory
    tracker_dir = Path(__file__).parent.parent.parent
    
    # Start the tracker daemon
    process = subprocess.Popen(
        [sys.executable, "-m", "tracker.main"],
        cwd=tracker_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait for it to start up
    time.sleep(2)
    
    assert process.poll() is None, "Tracker failed to start"
    
    # Send SIGTERM
    process.send_signal(signal.SIGTERM)
    
    try:
        # Wait for graceful shutdown (timeout 5s)
        stdout, stderr = process.communicate(timeout=5)
        
        print("STDOUT:", stdout)
        print("STDERR:", stderr)
        
        # Check return code is 0 (graceful exit)
        assert process.returncode == 0, f"Expected return code 0, got {process.returncode}"
        
        # Verify no crash trace in stderr
        assert "OC_PythonException" not in stderr, "Found PyObjC exception in stderr!"
        
    except subprocess.TimeoutExpired:
        process.kill()
        assert False, "Tracker did not shut down within 5 seconds of SIGTERM"

if __name__ == "__main__":
    test_graceful_shutdown()
    print("test_graceful_shutdown passed")
