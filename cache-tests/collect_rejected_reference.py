"""Measure text throughput after a recorded OCR rejection; never qualify it."""
import argparse
from run_suite import Suite, timestamp


class RejectedReferenceSuite(Suite):
    def features(self):
        try:
            return super().features()
        except RuntimeError as error:
            if str(error) != 'Feature check failed: vision_ocr':
                raise
            self.save('reference-feature-rejection.json', {
                'timestamp':timestamp(),'qualified':False,'error':str(error),
                'note':'OCR failure is preserved in lmcache-features.json. Remaining feature checks did not run. Text timing collection continues for this rejected reference only.'})
            print('Reference rejected for vision_ocr; collecting text timing only',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='/results')
    parser.add_argument('--config',default='/suite/run-config.json')
    parser.add_argument('--dataset',default='/data/longbench-canary.json')
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--lengths',type=int,nargs='+',default=[32000,128000,261000])
    parser.add_argument('--concurrency',action='store_true')
    RejectedReferenceSuite(parser.parse_args()).run()
