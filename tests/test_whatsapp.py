from nova.whatsapp import endpoint,NOTICE
def test_endpoint_requires_https_and_blocks_private_hosts():
 assert endpoint("https://agent.example.com/api").scheme=="https"
 for u in ["http://agent.example.com","https://localhost/api","https://127.0.0.1/api","https://user:pass@agent.example.com"]:
  try:endpoint(u)
  except ValueError:pass
  else:raise AssertionError("unsafe endpoint accepted")
def test_notice_discloses_non_end_to_end_encryption():
 assert "not consider these chats end-to-end encrypted" in NOTICE
