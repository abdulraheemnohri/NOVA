from nova.agent_tools import calculator
def test_calculator_is_not_code_execution():
 assert calculator("(2+3)*4")==20
 for x in ["__import__('os').system('id')","open('/etc/passwd').read()","x+1"]:
  try:calculator(x)
  except (ValueError,SyntaxError):pass
  else:raise AssertionError("unsafe expression accepted")
