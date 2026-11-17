File {
  Grid = "smoke_msh.tdr"
  Current = "smoke_des.plt"
  Plot = "smoke_des.tdr"
  Output = "smoke_des.log"
}

Electrode {
  { Name = "top" Voltage = 0.0 }
  { Name = "bottom" Voltage = 0.0 }
}

Physics {
  Temperature = 300
  Mobility(PhuMob HighFieldSaturation(GradQuasiFermi))
  Recombination(SRH)
  EffectiveIntrinsicDensity(BandGapNarrowing(OldSlotboom))
  Fermi
}

Plot {
  TotalCurrent/Vector eCurrent/Vector hCurrent/Vector
  ElectricField/Vector Potential SpaceCharge
  DopingConcentration
}

Math {
  Extrapolate
  RelErrControl
  ErrRef(electron) = 1e8
  ErrRef(hole) = 1e8
  Iterations = 20
  NotDamped = 50
  Digits = 5
  Method = ParDiSo
  NumberOfThreads = 4
  ParallelLicense(Wait)
  ExitOnFailure
  Wallclock
}

Solve {
  Coupled(Iterations = 100 LineSearchDamping = 1e-4) { Poisson }
  Coupled(Iterations = 100) { Poisson Electron Hole }
  Quasistationary(
    InitialStep = 1e-3 Increment = 1.41
    MinStep = 1e-7 MaxStep = 0.1
    Goal { Name = "top" Voltage = 0.1 }
  ) {
    Coupled { Poisson Electron Hole }
  }
}
