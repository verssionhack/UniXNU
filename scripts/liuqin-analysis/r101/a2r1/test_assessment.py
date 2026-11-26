import unittest
from assessment import decision
class Assessment(unittest.TestCase):
 def report(self):return {'a2_contract':{'snapshot_complete':True,'all_8_cpu_readbacks':True},'observer_budget_ok':True,'overlong_observer_lines':[],'status':'captured-observers; blocked-object attribution requires review'}
 def test_good(self):self.assertEqual(decision(self.report(),False)['exit_code'],0)
 def test_missing(self):
  r=self.report();r['a2_contract']['snapshot_complete']=False;self.assertEqual(decision(r,False)['exit_code'],5)
 def test_terminal_disconnect(self):self.assertEqual(decision(self.report(),True)['exit_code'],5)
 def test_source_contract_failed(self):
  r=self.report();r['status']='boot-or-observer-contract-failed';self.assertEqual(decision(r,False)['exit_code'],5)
 def test_no_boolean_contract(self):
  r=self.report();r['a2_contract']={};self.assertEqual(decision(r,False)['exit_code'],5)
 def test_budget(self):
  r=self.report();r['observer_budget_ok']=False;self.assertEqual(decision(r,False)['exit_code'],5)
if __name__=='__main__':unittest.main()
