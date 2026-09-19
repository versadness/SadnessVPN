"""Exercise the real desktop WebView with read-only UI scenarios."""
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main
from ui import window_control


def exercise():
    deadline = time.monotonic() + 35
    while window_control.controller is None and time.monotonic() < deadline:
        time.sleep(.1)
    control = window_control.controller
    if control is None or not control.ready.wait(30):
        print("SMOKE_FAILED: startup", flush=True)
        return
    control.silent = False
    control.show()
    window = control.window
    results = []
    try:
        for width, height in [(980,700),(780,600),(1400,900)]:
            window.resize(width,height)
            for page in ("home","servers","wg","routing","settings","zapret"):
                window.evaluate_js(f"go('{page}')")
                time.sleep(.12)
                result = window.evaluate_js("""
                  (() => {
                    const p=document.querySelector('.page.active');
                    const r=p.getBoundingClientRect();
                    return {page:p.id,viewport:[innerWidth,innerHeight],
                      horizontalOverflow:p.scrollWidth>p.clientWidth+1,
                      contentWidth:Math.round(r.width),
                      rulesHeight:p.id==='page-routing'?Math.round(p.querySelector('.scroll').getBoundingClientRect().height):null};
                  })()
                """)
                results.append(result)
        window.resize(980,700)
        window.evaluate_js("go('home')")
        initial_size=window.evaluate_js("[innerWidth,innerHeight]")
        for index in range(10):
            control.minimize()
            time.sleep(.15)
            control.show()
            time.sleep(.15)
            assert window.evaluate_js("document.getElementById('connectBtn').getBoundingClientRect().width") > 80
            current_size=window.evaluate_js("[innerWidth,innerHeight]")
            assert current_size == initial_size, f"Restore changed window size: {initial_size} -> {current_size}"
        for index in range(5):
            control.toggle_maximize();time.sleep(.15)
            control.toggle_maximize();time.sleep(.15)
            assert window.evaluate_js("[innerWidth,innerHeight]") == initial_size, "Maximize/restore changed size"
        window.evaluate_js("""
          window.__frameDeltas=[];window.__lastFrame=0;
          function sampleFrame(t){if(window.__lastFrame)__frameDeltas.push(t-__lastFrame);__lastFrame=t;if(__frameDeltas.length<180)requestAnimationFrame(sampleFrame);}
          requestAnimationFrame(sampleFrame);
        """)
        time.sleep(4)
        timing = window.evaluate_js("""
          (()=>{const a=__frameDeltas.slice().sort((a,b)=>a-b);return {samples:a.length,
          p95Ms:a[Math.floor(a.length*.95)],over50Ms:a.filter(t=>t>50).length,
          maxMs:Math.max(...a)};})()
        """)
        print("LAYOUT="+json.dumps(results), flush=True)
        print("RESTORE_CYCLES=10", flush=True)
        print("FRAME_TIMING="+json.dumps(timing), flush=True)
        print("SMOKE_OK" if not any(r["horizontalOverflow"] for r in results) else "SMOKE_OVERFLOW", flush=True)
    except Exception as exc:
        print("SMOKE_FAILED="+repr(exc), flush=True)
    # Leave the last screen visible for an independent visual inspection.


threading.Thread(target=exercise,daemon=True).start()
main.main()
