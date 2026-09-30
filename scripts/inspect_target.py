"""Read-only report through the production adapter. Never prints draft content."""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hey_gpt.settings import load_selectors
from hey_gpt.windows import WindowsAdapter, title

def main():
    if hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser()
    parser.add_argument("--hwnd",type=int,required=True)
    args=parser.parse_args()
    adapter=WindowsAdapter(load_selectors(Path(os.environ["LOCALAPPDATA"])/"HeyGPT"/"selectors.json")[0])
    adapter.bind_window(args.hwnd)
    print("Target valid:","chatgpt" in adapter.window_title.lower())
    print("Browser tab bound:",adapter.tab is not None)
    print("Selected page tabs excluded:",sum(c.ControlTypeName=="TabItemControl" and not adapter.browser_tab(c) for c in adapter.controls()))
    for role in ("composer","microphone","finish","send"):
        control=adapter.find(role,optional=True,require_foreground=False)
        print(role,"visible:",control is not None)
        if role=="composer" and control:
            for method in ("GetValuePattern","GetTextPattern","GetLegacyIAccessiblePattern"):
                try:
                    pattern=getattr(control,method)()
                    value=pattern.DocumentRange.GetText(-1) if method=="GetTextPattern" else pattern.Value
                    print(method,"empty:",not bool(value.strip()),"hint:",value.strip()==control.Name.strip())
                except Exception as error:
                    print(method,type(error).__name__)
    print("Production read_text empty:",not bool(adapter.read_text().strip()))

if __name__=="__main__":main()
