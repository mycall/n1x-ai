using System.Text;
using System.Text.Json.Nodes;
using N1x.Benchmarks;

static class CampaignTests
{
    internal static async Task Run(string folder)
    {
        Directory.CreateDirectory(folder);
        static void Require(bool condition,string message){if(!condition)throw new Exception(message);}
        var setting=new Campaign96.Settings(15,false,4096);
        byte[] original=Encoding.UTF8.GetBytes("@{\r\n    Image = 'image-id'\r\n    RequiredPartitionMiB = 98304\r\n}\r\n");
        byte[] variant=setting.Apply(original);string updated=Encoding.UTF8.GetString(variant);
        Require(updated.Contains("Image = 'image-id'")&&updated.Contains("RequiredPartitionMiB = 98304")&&updated.Contains("KvCacheBytes = '16106127360'")&&updated.Contains("UseLMCache = $false"),"Campaign variant lost a setting");
        updated=Encoding.UTF8.GetString(setting.Apply(Encoding.UTF8.GetBytes("@{\n 'KvCacheBytes' = '1' # old\n UseLMCache = $true\n BatchedTokens = 1\n}\n")));
        Require(updated.Split("KvCacheBytes").Length==2&&updated.Contains("BatchedTokens = 4096")&&!updated.Contains("# old"),"Campaign variant duplicated a setting");
        try{setting.Apply(Encoding.UTF8.GetBytes("@{\n UseLMCache = $true\n UseLMCache = $false\n}\n"));throw new Exception("Ambiguous controls accepted");}catch(InvalidDataException){}
        string config=Path.Combine(folder,"config.local.psd1");
        File.WriteAllBytes(config,original);Campaign96.ReplaceConfig(config,original,variant);Campaign96.ReplaceConfig(config,variant,original);
        Require(File.ReadAllBytes(config).SequenceEqual(original),"Campaign failed to restore original bytes");
        try{Campaign96.ReplaceConfig(config,variant,variant);throw new Exception("Overwrote external edit");}catch(IOException){}
        Require(File.ReadAllBytes(config).SequenceEqual(original),"External edit lost");
        var control=Data.Obj(new{results=new[]{new{concurrency=2,planned_tasks=24,correct_tasks=24,correct_tasks_s=.02},new{concurrency=4,planned_tasks=24,correct_tasks=24,correct_tasks_s=.02}}});
        var candidate=control.DeepClone().AsObject();
        Require(Campaign96.Qualified(control),"Complete control did not qualify");
        candidate["results"]![0]!["correct_tasks"]=23;
        Require(!Campaign96.Qualified(candidate),"Incorrect tasks qualified");
        candidate["results"]![0]!["correct_tasks_s"]=.04;candidate["results"]![1]!["correct_tasks_s"]=.01;
        var ratios=Campaign96.Comparisons(control,candidate);
        Require((double)ratios[0]!["throughput_ratio"]! ==2&&(double)ratios[1]!["throughput_ratio"]! ==.5,"Concurrency groups were mixed");
        control["results"]![0]!["correct_tasks_s"]=0.0;
        Require(Campaign96.Comparisons(control,candidate)[0]!["throughput_ratio"]==null,"Zero speed produced a ratio");
        candidate["results"]!.AsArray().RemoveAt(1);
        Require(!Campaign96.Qualified(candidate),"Incomplete campaign qualified");
        foreach(bool retry in new[]{false,true})
        {
            var labels=new List<string>();
            Task<int> Worker(string label)
            {
                labels.Add(label);return labels.Count==1?Task.FromException<int>(new Campaign96.TransportFailure("transport")):Task.FromResult(1);
            }
            try{await Campaign96.Retry("trial",Worker,(e,i,n)=>Task.FromResult(retry));Require(retry,"Failed attempt masked");}
            catch(Campaign96.TransportFailure)when(!retry){}
            Require(labels.SequenceEqual(retry?["trial-attempt1","trial-attempt2"]:new[]{"trial-attempt1"}),"Retry reused an attempt directory");
        }
        // A STOP file exercises the normal campaign entry point, including lock release
        // and evidence writing, without starting any service or touching the user's config.
        string output=Path.Combine(folder,"trial");
        foreach(string source in new[]{"Client/Campaign96.cs","Client/Campaign96Run.cs","campaign96_host.ps1","NearFullToolsReport.cs","Client/LongTools.cs"})
        {
            string file=Path.Combine(folder,"benchmarks",source);Directory.CreateDirectory(Path.GetDirectoryName(file)!);File.WriteAllText(file,"fixture");
        }
        Directory.CreateDirectory(output);File.WriteAllText(Path.Combine(output,"STOP"),"");
        try{await new Campaign96(folder,["--out",output]).Run();throw new Exception("STOP ignored");}catch(IOException ex)when(ex.Message.Contains("STOP")){}
        var summary=Data.Read(Path.Combine(output,"summary.json"));
        Require((bool)summary["original_configuration_restored"]! && File.ReadAllBytes(config).SequenceEqual(original) && !File.Exists(Path.Combine(folder,".state","campaign96.lock")),"Campaign STOP cleanup failed");
    }
}
