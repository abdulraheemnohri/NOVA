from pydantic import ValidationError
from nova.updates import UpdateConfig
def test_update_interval_is_bounded():
 for hours in (0,25):
  try:UpdateConfig(interval_hours=hours)
  except ValidationError:pass
  else:raise AssertionError("invalid update interval accepted")
 assert UpdateConfig(interval_hours=6).interval_hours==6
