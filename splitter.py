#   Copyright 2011-2012 Opera Software ASA 
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

'''
Created on 5. apr. 2011

@author: Yngve
'''

import sys, os.path
import optparse
import subprocess

class Splitter:
	def __init__(self):
		self.logging_enabled =True
		self.last_rev = None
		self.tree_commits = {}
		self.annotate = None
		
	def _check_output(self, args, shell=True, input=None, *pargs, **kwargs):
		"""
		Perform requested system command as a piped operation, parse result 
		into an array of lines
		"""
		self.log("_check_output:", args)
		self.log("cwd:", os.getcwd())
		self.log("-----")
		x = subprocess.Popen(" ".join(args) if shell else args, *pargs, shell=shell,stdin=subprocess.PIPE, stdout=subprocess.PIPE, **kwargs).communicate(input)
		y = x[0].splitlines()
		self.log("-----")
		return y

	def _call(self, *args, **kwargs):
		"""Perform the requested system command, return the call result"""
		self.log("_call:",args)
		self.log("cwd:", os.getcwd())
		self.log("-----")
		ret = subprocess.call(*args, stdin=subprocess.PIPE, **kwargs)
		self.log("-----")
		self.log(ret)
		return ret
	
	def _tag_commit(self, commit, *tags):
		"""Tag a commit"""
		for tag in tags:
			if self._call(["git", "tag", "-f", tag, commit]) != 0 :
				raise BaseException("Could not tag commit %s with %s"% (commit, tag))

	def log(self,*arg):
		if self.logging_enabled:
			print " ".join([str(x) for x in arg])
			
	def check_repo(self,targetrepo, create=True):
		"""
		Check if the repo is a valid Git repo, optionally initializing a
		bare repository
		"""

		pwd = os.getcwd()
		if os.path.exists(targetrepo):
			if not os.path.isdir(targetrepo):
				raise BaseException(targetrepo +" is not a directory")
		
			try:
				os.chdir(targetrepo)
				if os.path.isdir(".git"):
					if self._check_output(["git","rev-parse", "--is-inside-work-tree"])[0].lower() != "true":
						raise BaseException(targetrepo +" is not a git repository")
				else:
					if self._check_output(["git","rev-parse", "--is-bare-repository"])[0].lower() != "true":
						raise BaseException(targetrepo +" is not a git repository")
			finally:
				os.chdir(pwd)
	
		elif create:
			if self._call(["git", "init", "--bare", targetrepo]) != 0 :
				raise BaseException("Could not initialize git repository "+targetrepo)
		
	
	def _insert_tree(self, rev, tree, new_parents):
		"""
		Insert a file tree as a commit into the repository branch,
		connecting it to its parent commit(s), copying the log 
		entry from the original commit
		"""
		got_parents = []

		identical = None		
		for parent in new_parents:
			if parent not in self.tree_commits:
				ptree = self._check_output(["git","log", "-1", "--pretty=format:%T", '"' + parent + '"', "--"])
				if not ptree:
					continue
				ptree = ptree[0]
				self.tree_commits[parent] = ptree
			else:
				ptree = self.tree_commits[parent]

			if tree == ptree:
				identical = parent
	
			got_parents.append(parent)
	
		if identical:
			return identical 

		return self._insert_commit(rev, tree, got_parents)
		
	def _insert_commit(self, rev, tree, new_parents):
		"""
		Insert a commit into the repository branch, connecting it to its
		parent commit(s), copying the log entry from the original commit
		"""
		
		env = dict(os.environ)
		
		log_entry = self._check_output([ "git","log","-1", "--pretty=format:%an%n%ae%n%ad%n%cn%n%ce%n%cd%n%s%n%n%b", rev ], shell=False)
		if not log_entry or len(log_entry) <7:
			raise BaseException("Wrong log entry")
		
		env["GIT_AUTHOR_NAME"] = log_entry[0] 
		env["GIT_AUTHOR_EMAIL"] = log_entry[1] 
		env["GIT_AUTHOR_DATE"] = log_entry[2] 
		env["GIT_COMMITTER_NAME"] = log_entry[3] 
		env["GIT_COMMITTER_EMAIL"] = log_entry[4] 
		env["GIT_COMMITTER_DATE"] = log_entry[5]
		
		message = (self.annotate if self.annotate else "") + "\n".join(log_entry[6:])+"\n"
		
		parents = []
		for x in new_parents:
			parents += ["-p", x] 
	
		commit_id = self._check_output(["git","commit-tree", tree] + parents, env=env, input=message)
		if not commit_id:
			raise BaseException("Could not copy commit "+rev)
		
		self.tree_commits[commit_id[0]] = tree
		return commit_id[0]
		
	def split(self, options, rev_args):
		"""
		Split the specified subdirectory off as a submodule, removing
		the leading path prefix
		"""
	
		revs = self._check_output(["git","rev-parse", "--default", "HEAD", "--revs-only"]+rev_args)
		
		self.log("Revision list", revs)
	
		if self._check_output(["git","rev-parse", "--default", "HEAD", "--no-revs", "--no-flags"]+rev_args):
			raise BaseException("Incorrect directory specification")
		
		targetrepo = options.push_repo
		pwd = os.getcwd()
		
		split_count = 0
	
		push_list = set()
		push_tags = {}
		target_commit_list = {}
		tag_list = {}
		tree_commits={}
		tagged_commits=set()
	
		if options.onto_name:
			revlist = self._check_output(["git","rev-list", options.onto_name])
			for rev in revlist:
				target_commit_list[rev]=rev

		#Extract list of commit to tag  mappings
		tag_data = self._check_output(["git","show-ref", "--tags",])
		for line in tag_data:
			items = line.split()
			rev = items[0]
			ref = items[1].split("/")
			if len(ref) != 3:
				continue
			
			tag_list.setdefault(rev, []).append(ref[2])

		if options.tag_name:
			#Extract list of tag_name-x-commit  mappings, to reduce unnecessary conversions
			for rev, tags in tag_list.iteritems():
				
				for tag in tags:
					if not tag.startswith(options.tag_name+"-x-"):
						continue
					ref = tag[len(options.tag_name):].split("-")
					if len(ref) != 3:
						continue
					target_commit_list[ref[2]]=rev

		#Extract list of commits to process					
		revlist = self._check_output(["git","rev-list", "--reverse", "--parents"] + revs)

		revlist1 = []		
		for line in revlist:
			items = line.split()
			rev = items[0]
			parents = items[1:]
			revlist1.append((rev, parents))
			
		revlist = revlist1
		revlist1 = []
		
		included = set()
		testable = set([revlist[-1][0]])
		i=0
		for (rev,parents) in reversed(revlist):
			if rev not in testable:
				continue
			testable.remove(rev)
			if rev not in target_commit_list:
				testable.update(parents)
				included.add(rev)
			else:
				#skip revision
				pass
				
		for (rev,parents) in revlist:
			if rev in included:
				revlist1.append((rev,parents))

		revlist = revlist1

		i=0
		for line in revlist:
			i+=1
			
		i = 0
		# Process list of revisions, converting them to the new submodule on the target branch
		for rev,parents in revlist:
			i+=1
			self.log("Processing ", rev)
			
			if rev in target_commit_list:
				# Already converted, no need to do anything
				mapping_rev =  target_commit_list[rev]
				self.log("Already processed", rev," as " ,mapping_rev)
				continue
			
			split_count += 1

			tree_list = self._check_output(["git","ls-tree", rev,  '"' + options.prefix_name + '"'])
			if not tree_list:
				continue
				
			tree_elem = tree_list[0].split()[2]
			self.log("tree is",tree_elem)

			new_parents = [target_commit_list[x] for x in parents if x in target_commit_list]
			self.log("Aliases for", parents, "are", new_parents)
	
			new_rev = self._insert_tree(rev, tree_elem, new_parents)
			
			if options.tag_name and (new_rev not in tagged_commits or len(parents) != len(new_parents)):
				tag_name = options.tag_name+"-x-" + rev
				self._tag_commit(new_rev, tag_name)
				self.log("Tagged" ,new_rev, " as " ,tag_name)
				push_list.add(tag_name)
				tagged_commits.add(new_rev)
				
			target_commit_list[rev]=new_rev
			self.last_rev = new_rev
				
			for tag in tag_list.get(rev,[]):
				push_tags[tag] = new_rev 

		if not self.last_rev:
			print  "No revisions found"
			return
	
		branch_name = options.branch_name
		if not branch_name:
			branch_name = "split_repo"
			
		if self._call(["git","branch", "-f", branch_name, self.last_rev]) != 0:
			raise BaseException("Could not create branch %s for %s" %(branch_name, self.last_rev))
	
		if targetrepo:
			rev_list = list(push_list) + [new_rev +":refs/tags/" + tag for tag, new_rev in push_tags.iteritems()]
			
			n = len(rev_list)
			for i in range(0, n, 100):
				if self._call(["git","push", targetrepo, branch_name, ] + 
							rev_list[i:(i+100 if i + 100 <= n else 100)]
							) != 0:
					raise BaseException("Could not push tags and branches")

	def replant(self, options, rev_args):
		"""
		Process each specified commit, relocate its files in the specified 
		folder, and optionally export it to the target repo
		"""
		
		self._call(["git","branch", "-D", "subtree_replant_temp"])
		self._call(["git","symbolic-ref","HEAD", "refs/heads/subtree_replant_temp"])
	
		revs = self._check_output(["git","rev-parse", "--default", "HEAD", "--revs-only"]+rev_args)
		is_bare = self._check_output(["git", "rev-parse", "--is-bare-repository"])[0].lower() == "true"
		if is_bare:
			raise BaseException("Can't be a bare repository")
		
		self.log("Revision list", revs)
	
		if self._check_output(["git","rev-parse", "--default", "HEAD", "--no-revs", "--no-flags"]+rev_args):
			raise BaseException("Incorrect directory specification")
		
		targetrepo = options.push_repo
		pwd = os.getcwd()
		
		split_count = 0
	
		push_list = set()
		push_tags = {}
		target_commit_list = {}
		tag_list = {}
		tree_commits={}
		tagged_commits=set()
		source_commit_list = {}
		map_source_commit_list = {}
		#Extract list of commit to tag  mappings
		tag_data = self._check_output(["git","show-ref", "--tags",])
		for line in tag_data:
			items = line.split()
			rev = items[0]
			ref = items[1].split("/")
			if len(ref) != 3:
				continue
			
			tag_list.setdefault(rev, []).append(ref[2])

		if options.tag_name:
			#Extract list of tag_name-x-commit  mappings, to reduce unnecessary conversions
			for rev, tags in tag_list.iteritems():
				
				for tag in tags:
					if not tag.startswith(options.tag_name+"-x-"):
						continue
				
					ref = tag[len(options.tag_name):].split("-")
					if len(ref) == 3:
						source_commit_list.setdefault(rev,[]).append(tag)
						
					elif len(ref) == 4 and not ref[2]:
						map_source_commit_list[ref[3]] = rev
						target_commit_list[ref[3]] = rev
				
		
		#extract list of revisions
		revlist = self._check_output(["git","rev-list", "--reverse", "--parents"] + revs)
		
		i=0
		for line in revlist:
			i+=1
			
		i = 0
		for line in revlist:
			#take each commit filetree and prefix it with the folder name, and insert it in the target branch  
			i+=1
			items = line.split()
			rev = items[0]
			parents = items[1:]
			self.log("Processing ", rev)
			
			if rev in map_source_commit_list:
				self.log("Already processed", rev)
				continue
			
			split_count += 1

			os.unlink(os.path.join(".git","index"))
			self._call(["git", "clean", "-fdx"])
				
			self._check_output(["git","read-tree", "--prefix="+options.prefix_name, "-u", rev])
			tree_elem = self._check_output(["git","write-tree"])
			if not tree_elem:
				continue
			
			tree_elem = tree_elem[0]

			new_parents = [target_commit_list[x] for x in parents if x in target_commit_list]
			self.log("Aliases for", parents, "are", new_parents)
	
			new_rev = self._insert_commit(rev, tree_elem, new_parents)
			
			if options.tag_name and new_rev not in tagged_commits:
				for tag in source_commit_list.get(rev,[]):
					tag_name = tag +"-" + rev
					self._tag_commit(new_rev, tag_name)
					self.log("Tagged" ,new_rev, " as " ,tag_name)
					push_list.add(tag_name)
				tag_name = options.tag_name+"-x--" + rev
				self._tag_commit(new_rev, tag_name)
				self.log("Tagged" ,new_rev, " as " ,tag_name)
				push_list.add(tag_name)
				tagged_commits.add(new_rev)
				
			target_commit_list[rev]=new_rev
			self.last_rev = new_rev

		if not self.last_rev:
			print  "No revisions found"
			return
	
		branch_name = options.branch_name
		if not branch_name:
			branch_name = "split_repo"
			
		if self._call(["git","branch", "-f", branch_name, self.last_rev]) != 0:
			raise BaseException("Could not create branch %s for %s" %(branch_name, self.last_rev))
	
		if targetrepo:
			rev_list = list(push_list) + [new_rev +":" + tag for tag, new_rev in push_tags.iteritems()]
			
			n = len(rev_list)
			for i in range(0, n, 100):
				if self._call(["git","push", targetrepo, branch_name, ] + 
							rev_list[i:(i+100 if i + 100 <= n else 100)]
							) != 0:
					raise BaseException("Could not push tags and branches")
	
	
	
	def start(self, varg=None):
		"""Start the selected operation, with the requested parameters"""

		optionsConfig =optparse.OptionParser(usage="splitter action [options] revs")
		
		optionsConfig.add_option("--prefix", action="store", type="string", dest="prefix_name")
		optionsConfig.add_option("--branch", action="store", type="string", dest="branch_name")
		optionsConfig.add_option("--onto", action="store", type="string", dest="onto_name")
		optionsConfig.add_option("--tag", action="store", type="string", dest="tag_name")
		optionsConfig.add_option("--push", action="store", type="string", dest="push_repo")
		optionsConfig.add_option("--repo", action="store", type="string", dest="work_repo")
		
		
		options, args = optionsConfig.parse_args(varg)
		
		if len(args) == 0:
			print "No action specified"
			return
		
		action = args[0]
		revs = args[1:] if len(args)>1 else ["master"]

		# check prefix
		if not options.prefix_name:
			raise BaseException("No prefix path provided")
		
		options.prefix_name.replace('\\', '/')
		if options.prefix_name.endswith('/'):
			options.prefix_name = options.prefix_name[0:-1]
 
	
		# check work repo
		if options.work_repo:
			os.chdir(options.work_repo)

		self.check_repo(os.getcwd(), create = False)		
	
		# Check target repo	
		targetrepo = options.push_repo
		if not targetrepo:
			raise BaseException("No target repo")

		self.check_repo(targetrepo)		
	
		if action == "split":
			self.split(options,revs)
		elif action == "replant":
			self.replant(options,revs)

	
	
if __name__ == '__main__':

	splitter = Splitter()
	
	splitter.start()