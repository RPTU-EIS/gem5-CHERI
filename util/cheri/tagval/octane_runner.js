// Fixed-iteration runner for Octane under Duktape (instead of base.js's
// time-based BenchmarkSuite.RunSuites): every benchmark of every suite
// loaded before this file runs Setup, __iterations runs, TearDown, with
// base.js's deterministic Math.random, so all ABIs do the same work.
(function () {
  BenchmarkSuite.ResetRNG();
  var suites = BenchmarkSuite.suites;
  for (var s = 0; s < suites.length; s++) {
    var bms = suites[s].benchmarks;
    for (var b = 0; b < bms.length; b++) {
      var bm = bms[b];
      bm.Setup();
      for (var i = 0; i < __iterations; i++)
        bm.run();
      bm.TearDown();
      print(suites[s].name + "/" + bm.name + ": " + __iterations +
            " iterations");
    }
  }
})();
