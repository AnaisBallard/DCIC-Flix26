import sys
import types
from pathlib import Path

app_directory = Path(__file__).resolve().parents[1] / "app"
package = types.ModuleType("dcic_recommendation_app")
package.__path__ = [str(app_directory)]
sys.modules.setdefault("dcic_recommendation_app", package)
