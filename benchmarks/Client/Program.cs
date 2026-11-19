using N1x.Benchmarks;

try
{
    if (args.FirstOrDefault() == "speed") await new SpeedProbe(args[1..]).Run();
    else if (args.FirstOrDefault() is "scheduler" or "speculation") await ShortProbes.Run(args[0], args[1..]);
    else if (args.FirstOrDefault() is "agent" or "mixed" or "recovery" or "restart") await Qualification.Run(args[0], args[1..]);
    else if (args.FirstOrDefault() == "campaign96") await new Campaign96(RecipeHost.Root(), args[1..]).Run();
    else if (args.FirstOrDefault() == "capacity") await Capacity.Run(args[1..]);
    else if (args.FirstOrDefault() is "near-full" or "displaced") { bool replay = args[0] == "displaced"; using var probe = new LongTools(args[1..], replay); await probe.Run(replay); }
    else if (args.FirstOrDefault() == "recipe-repeats") await RecipeRepeats.Run(args[1..]);
    else if (args.FirstOrDefault() == "recipe-queue") await RecipeQueue.Run(args[1..]);
    else if (args.FirstOrDefault() == "recipe-trial") await RecipeTrial.Run(args[1..]);
    else if (args.FirstOrDefault() == "recipe-quality") await RecipeQuality.Run(args[1..]);
    else if (args.FirstOrDefault() == "matrix") await SpeedMatrix.Run(args[1..]);
    else if (args.FirstOrDefault() == "matrix-report") MatrixReport.Run(args[1..]);
    else if (args.FirstOrDefault() == "suite") await new BenchmarkSuite(args[1..]).Run();
    else if (args.FirstOrDefault() == "speed-report")
    {
        var options = new Options(args[1..], [], ["--runs"], ["--out"]);
        var directories = options.List("--runs");
        if (directories.Length == 0) throw new ArgumentException("Expected --runs DIRECTORY...");
        var runs = directories.Select(SpeedReport.Load).ToArray();
        string output = options.Get("--out");
        Data.NewFolder(output);
        SpeedReport.Write(runs, output);
        Console.WriteLine(Path.Combine(output, "comparison.md"));
    }
    else throw new ArgumentException("Expected speed or speed-report");
    return 0;
}
catch (Exception error)
{
    Console.Error.WriteLine(error.Message);
    return 1;
}
