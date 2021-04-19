import os
from abc import ABC, abstractmethod
from itertools import chain, combinations


class BaseExperiment(ABC):
    def __init__(self, flags):
        self.flags = flags
        self.name = flags.dataset

        self.modalities = None
        self.num_modalities = None
        self.subsets = None
        self.dataset_train = None
        self.dataset_test = None

        self.mm_vae = None
        self.clfs = None
        self.optimizer = None
        self.rec_weights = None
        self.style_weights = None

        self.test_samples = None
        self.paths_fid = None

    @abstractmethod
    def set_model(self):
        pass

    @abstractmethod
    def set_modalities(self):
        pass

    @abstractmethod
    def set_dataset(self):
        pass

    @abstractmethod
    def set_clfs(self):
        pass

    @abstractmethod
    def set_optimizer(self):
        pass

    @abstractmethod
    def set_rec_weights(self):
        pass

    @abstractmethod
    def set_style_weights(self):
        pass

    @abstractmethod
    def get_test_samples(self):
        pass

    @abstractmethod
    def mean_eval_metric(self, values):
        pass

    @abstractmethod
    def eval_label(self, values, labels, index=None):
        pass

    def set_subsets(self):
        """
        powerset([1,2,3]) --> () (1,) (2,) (3,) (1,2) (1,3) (2,3)
        (1,2,3)
        >>> exp.modalities = {'a':None, 'b':None, 'c':None}
        >>> exp.set_subsets()
        {'': [], 'a': [None], 'b': [None], 'c': [None], 'a_b': [None, None], 'a_c': [None, None], 'b_c': [None, None], 'a_b_c': [None, None, None]}
        """
        xs = list(self.modalities)
        # note we return an iterator rather than a list
        subsets_list = chain.from_iterable(combinations(xs, n) for n in
                                           range(len(xs) + 1))
        subsets = {}
        for k, mod_names in enumerate(subsets_list):
            mods = [self.modalities[mod_name] for mod_name in sorted(mod_names)]
            key = '_'.join(sorted(mod_names))
            subsets[key] = mods
        return subsets

    def set_paths_fid(self):
        dir_real = os.path.join(self.flags.dir_gen_eval_fid, 'real')
        dir_random = os.path.join(self.flags.dir_gen_eval_fid, 'random')
        paths = {'real': dir_real,
                 'random': dir_random}
        dir_cond = self.flags.dir_gen_eval_fid
        for name in self.subsets:
            paths[name] = os.path.join(dir_cond, name)
        return paths